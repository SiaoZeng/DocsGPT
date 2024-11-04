import conversationService from '../api/services/conversationService';
import userService from '../api/services/userService';
import { Doc } from '../models/misc';

//Fetches all JSON objects from the source. We only use the objects with the "model" property in SelectDocsModal.tsx. Hopefully can clean up the source file later.
export async function getDocs(
  sort = 'date',
  order = 'desc',
): Promise<Doc[] | null> {
  try {
    const response = await userService.getDocs(sort, order);
    const data = await response.json();

    const docs: Doc[] = [];

    data.forEach((doc: object) => {
      docs.push(doc as Doc);
    });

    return docs;
  } catch (error) {
    console.log(error);
    return null;
  }
}

export async function getConversations(): Promise<{
  data: { name: string; id: string }[] | null;
  loading: boolean;
}> {
  try {
    const response = await conversationService.getConversations();
    const data = await response.json();

    const conversations: { name: string; id: string }[] = [];

    data.forEach((conversation: object) => {
      conversations.push(conversation as { name: string; id: string });
    });

    return { data: conversations, loading: false };
  } catch (error) {
    console.log(error);
    return { data: null, loading: false };
  }
}

export function getLocalApiKey(): string | null {
  const key = localStorage.getItem('DocsGPTApiKey');
  return key;
}

export function getLocalRecentDocs(): string | null {
  const doc = localStorage.getItem('DocsGPTRecentDocs');
  return doc;
}

export function getLocalPrompt(): string | null {
  const prompt = localStorage.getItem('DocsGPTPrompt');
  return prompt;
}

export function setLocalApiKey(key: string): void {
  localStorage.setItem('DocsGPTApiKey', key);
}

export function setLocalPrompt(prompt: string): void {
  localStorage.setItem('DocsGPTPrompt', prompt);
}

export function setLocalRecentDocs(doc: Doc | null): void {
  localStorage.setItem('DocsGPTRecentDocs', JSON.stringify(doc));

  let docPath = 'default';
  if (doc?.type === 'local') {
    docPath = 'local' + '/' + doc.name + '/';
  }
  userService
    .checkDocs({
      docs: docPath,
    })
    .then((response) => response.json());
}
