import logging
import os
import shutil
import string
import zipfile
from collections import Counter
from urllib.parse import urljoin

import requests
from bson.objectid import ObjectId

from application.core.mongo_db import MongoDB
from application.core.settings import settings
from application.parser.file.bulk import SimpleDirectoryReader
from application.parser.embedding_pipeline import embed_and_store_documents
from application.parser.remote.remote_creator import RemoteCreator
from application.parser.schema.base import Document
from application.parser.chunking import Chunker
from application.utils import count_tokens_docs

mongo = MongoDB.get_client()
db = mongo["docsgpt"]
sources_collection = db["sources"]

# Constants
MIN_TOKENS = 150
MAX_TOKENS = 1250
RECURSION_DEPTH = 2

# Define a function to extract metadata from a given filename.
def metadata_from_filename(title):
    return {"title": title}

# Define a function to generate a random string of a given length.
def generate_random_string(length):
    return "".join([string.ascii_letters[i % 52] for i in range(length)])

current_dir = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

def extract_zip_recursive(zip_path, extract_to, current_depth=0, max_depth=5):
    """
    Recursively extract zip files with a limit on recursion depth.

    Args:
        zip_path (str): Path to the zip file to be extracted.
        extract_to (str): Destination path for extracted files.
        current_depth (int): Current depth of recursion.
        max_depth (int): Maximum allowed depth of recursion to prevent infinite loops.
    """
    if current_depth > max_depth:
        logging.warning(f"Reached maximum recursion depth of {max_depth}")
        return

    try:
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(extract_to)
        os.remove(zip_path)  # Remove the zip file after extracting
    except Exception as e:
        logging.error(f"Error extracting zip file {zip_path}: {e}")
        return

    # Check for nested zip files and extract them
    for root, dirs, files in os.walk(extract_to):
        for file in files:
            if file.endswith(".zip"):
                # If a nested zip file is found, extract it recursively
                file_path = os.path.join(root, file)
                extract_zip_recursive(file_path, root, current_depth + 1, max_depth)

def download_file(url, params, dest_path):
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        with open(dest_path, "wb") as f:
            f.write(response.content)
    except requests.RequestException as e:
        logging.error(f"Error downloading file: {e}")
        raise

def upload_index(full_path, file_data):
    try:
        if settings.VECTOR_STORE == "faiss":
            files = {
                "file_faiss": open(full_path + "/index.faiss", "rb"),
                "file_pkl": open(full_path + "/index.pkl", "rb"),
            }
            response = requests.post(
                urljoin(settings.API_URL, "/api/upload_index"), files=files, data=file_data
            )
        else:
            response = requests.post(
                urljoin(settings.API_URL, "/api/upload_index"), data=file_data
            )
        response.raise_for_status()
    except requests.RequestException as e:
        logging.error(f"Error uploading index: {e}")
        raise
    finally:
        if settings.VECTOR_STORE == "faiss":
            for file in files.values():
                file.close()

# Define the main function for ingesting and processing documents.
def ingest_worker(
    self, directory, formats, name_job, filename, user, retriever="classic"
):
    """
    Ingest and process documents.

    Args:
        self: Reference to the instance of the task.
        directory (str): Specifies the directory for ingesting ('inputs' or 'temp').
        formats (list of str): List of file extensions to consider for ingestion (e.g., [".rst", ".md"]).
        name_job (str): Name of the job for this ingestion task.
        filename (str): Name of the file to be ingested.
        user (str): Identifier for the user initiating the ingestion.
        retriever (str): Type of retriever to use for processing the documents.

    Returns:
        dict: Information about the completed ingestion task, including input parameters and a "limited" flag.
    """
    input_files = None
    recursive = True
    limit = None
    exclude = True
    sample = False
    full_path = os.path.join(directory, user, name_job)

    logging.info(f"Ingest file: {full_path}", extra={"user": user, "job": name_job})
    file_data = {"name": name_job, "file": filename, "user": user}

    if not os.path.exists(full_path):
        os.makedirs(full_path)
    download_file(urljoin(settings.API_URL, "/api/download"), file_data, os.path.join(full_path, filename))

    # check if file is .zip and extract it
    if filename.endswith(".zip"):
        extract_zip_recursive(
            os.path.join(full_path, filename), full_path, 0, RECURSION_DEPTH
        )

    self.update_state(state="PROGRESS", meta={"current": 1})

    raw_docs = SimpleDirectoryReader(
        input_dir=full_path,
        input_files=input_files,
        recursive=recursive,
        required_exts=formats,
        num_files_limit=limit,
        exclude_hidden=exclude,
        file_metadata=metadata_from_filename,
    ).load_data()

    chunker = Chunker(
        chunking_strategy="classic_chunk",
        max_tokens=MAX_TOKENS,
        min_tokens=MIN_TOKENS,
        duplicate_headers=False
    )
    raw_docs = chunker.chunk(documents=raw_docs)

    docs = [Document.to_langchain_format(raw_doc) for raw_doc in raw_docs]
    id = ObjectId()

    embed_and_store_documents(docs, full_path, id, self)
    tokens = count_tokens_docs(docs)
    self.update_state(state="PROGRESS", meta={"current": 100})

    if sample:
        for i in range(min(5, len(raw_docs))):
            logging.info(f"Sample document {i}: {raw_docs[i]}")

    file_data.update({
        "tokens": tokens,
        "retriever": retriever,
        "id": str(id),
        "type": "local",
    })
    upload_index(full_path, file_data)

    # delete local
    shutil.rmtree(full_path)

    return {
        "directory": directory,
        "formats": formats,
        "name_job": name_job,
        "filename": filename,
        "user": user,
        "limited": False,
    }

def remote_worker(
    self,
    source_data,
    name_job,
    user,
    loader,
    directory="temp",
    retriever="classic",
    sync_frequency="never",
    operation_mode="upload",
    doc_id=None,
):  
    full_path = os.path.join(directory, user, name_job)
    if not os.path.exists(full_path):
        os.makedirs(full_path)

    self.update_state(state="PROGRESS", meta={"current": 1})
    try:
        logging.info("Initializing remote loader with type: %s", loader)
        remote_loader = RemoteCreator.create_loader(loader)
        raw_docs = remote_loader.load_data(source_data)

        chunker = Chunker(
            chunking_strategy="classic_chunk",
            max_tokens=MAX_TOKENS,
            min_tokens=MIN_TOKENS,
            duplicate_headers=False
        )
        docs = chunker.chunk(documents=raw_docs)
        docs = [Document.to_langchain_format(raw_doc) for raw_doc in raw_docs]
        tokens = count_tokens_docs(docs)
        logging.info("Total tokens calculated: %d", tokens)

        if operation_mode == "upload":
            id = ObjectId()
            embed_and_store_documents(docs, full_path, id, self)
        elif operation_mode == "sync":
            if not doc_id or not ObjectId.is_valid(doc_id):
                logging.error("Invalid doc_id provided for sync operation: %s", doc_id)
                raise ValueError("doc_id must be provided for sync operation.")
            id = ObjectId(doc_id)
            embed_and_store_documents(docs, full_path, id, self)

        self.update_state(state="PROGRESS", meta={"current": 100})

        file_data = {
            "name": name_job,
            "user": user,
            "tokens": tokens,
            "retriever": retriever,
            "id": str(id),
            "type": loader,
            "remote_data": source_data,
            "sync_frequency": sync_frequency,
        }
        upload_index(full_path, file_data)

    except Exception as e:
        logging.error("Error in remote_worker task: %s", str(e), exc_info=True)
        raise

    finally:
        if os.path.exists(full_path):
            shutil.rmtree(full_path)

    logging.info("remote_worker task completed successfully")
    return {"urls": source_data, "name_job": name_job, "user": user, "limited": False}

def sync(
    self,
    source_data,
    name_job,
    user,
    loader,
    sync_frequency,
    retriever,
    doc_id=None,
    directory="temp",
):
    try:
        remote_worker(
            self,
            source_data,
            name_job,
            user,
            loader,
            directory,
            retriever,
            sync_frequency,
            "sync",
            doc_id,
        )
    except Exception as e:
        logging.error(f"Error during sync: {e}")
        return {"status": "error", "error": str(e)}
    return {"status": "success"}

def sync_worker(self, frequency):
    sync_counts = Counter()
    sources = sources_collection.find()
    for doc in sources:
        if doc.get("sync_frequency") == frequency:
            name = doc.get("name")
            user = doc.get("user")
            source_type = doc.get("type")
            source_data = doc.get("remote_data")
            retriever = doc.get("retriever")
            doc_id = str(doc.get("_id"))
            resp = sync(
                self, source_data, name, user, source_type, frequency, retriever, doc_id
            )
            sync_counts["total_sync_count"] += 1
            sync_counts[
                "sync_success" if resp["status"] == "success" else "sync_failure"
            ] += 1

    return {
        key: sync_counts[key]
        for key in ["total_sync_count", "sync_success", "sync_failure"]
    }

def attachment_worker(self, directory, file_info, user):
    """
    Process and store a single attachment without vectorization.
    
    Args:
        self: Reference to the instance of the task.
        directory (str): Base directory for storing files.
        file_info (dict): Dictionary with folder and filename info.
        user (str): User identifier.
        
    Returns:
        dict: Information about processed attachment.
    """
    import datetime
    import os
    from application.utils import num_tokens_from_string
    
    mongo = MongoDB.get_client()
    db = mongo["docsgpt"]
    attachments_collection = db["attachments"]
    
    job_name = file_info["folder"]
    logging.info(f"Processing attachment: {job_name}", extra={"user": user, "job": job_name})
    
    self.update_state(state="PROGRESS", meta={"current": 10})
    
    folder_name = file_info["folder"]
    filename = file_info["filename"]
    
    file_path = os.path.join(directory, filename)
    
    
    logging.info(f"Processing file: {file_path}", extra={"user": user, "job": job_name})
    
    if not os.path.exists(file_path):
        logging.warning(f"File not found: {file_path}", extra={"user": user, "job": job_name})
        return {"error": "File not found"}
    
    try:
        reader = SimpleDirectoryReader(
            input_files=[file_path]
        )
        
        documents = reader.load_data()
        
        self.update_state(state="PROGRESS", meta={"current": 50})
        
        if documents:
            content = documents[0].text
            token_count = num_tokens_from_string(content)
            
            file_path_relative = f"{user}/attachments/{folder_name}/{filename}"
            
            attachment_id = attachments_collection.insert_one({
                "user": user,
                "path": file_path_relative,
                "content": content,
                "token_count": token_count,
                "date": datetime.datetime.now(),
            }).inserted_id
            
            logging.info(f"Stored attachment with ID: {attachment_id}", 
                        extra={"user": user, "job": job_name})
            
            self.update_state(state="PROGRESS", meta={"current": 100})
            
            return {
                "attachment_id": str(attachment_id),
                "filename": filename,
                "folder": folder_name,
                "path": file_path_relative,
                "token_count": token_count
            }
        else:
            logging.warning("No content was extracted from the file", 
                           extra={"user": user, "job": job_name})
            return {"error": "No content was extracted from the file"}
    except Exception as e:
        logging.error(f"Error processing file {filename}: {e}", 
                     extra={"user": user, "job": job_name}, exc_info=True)
        return {"error": f"Error processing file: {str(e)}"}
