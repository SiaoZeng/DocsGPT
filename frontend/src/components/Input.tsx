import { InputProps } from './types';
import { useRef } from 'react';

const Input = ({
  id,
  name,
  type,
  value,
  isAutoFocused = false,
  placeholder,
  required = false,
  maxLength,
  className = '',
  colorVariant = 'silver',
  borderVariant = 'thick',
  children,
  labelBgClassName = 'bg-white dark:bg-raisin-black',
  onChange,
  onPaste,
  onKeyDown,
}: InputProps) => {
  const colorStyles = {
    silver: 'border-silver dark:border-silver/40',
    jet: 'border-jet',
    gray: 'border-gray-5000 dark:text-silver',
  };
  const borderStyles = {
    thin: 'border',
    thick: 'border-2',
  };

  const inputRef = useRef<HTMLInputElement>(null);

  return (
    <div className={`relative ${className}`}>
      <input
        ref={inputRef}
        className={`peer h-[42px] w-full rounded-full px-3 py-1 
          bg-transparent outline-none 
          text-jet dark:text-bright-gray
          placeholder-transparent 
          ${colorStyles[colorVariant]} 
          ${borderStyles[borderVariant]}
          [&:-webkit-autofill]:bg-transparent
          [&:-webkit-autofill]:appearance-none
          [&:-webkit-autofill_selected]:bg-transparent`}
        type={type}
        id={id}
        name={name}
        autoFocus={isAutoFocused}
        placeholder={placeholder || ''}
        maxLength={maxLength}
        value={value}
        onChange={onChange}
        onPaste={onPaste}
        onKeyDown={onKeyDown}
        required={required}
      >
        {children}
      </input>
      {placeholder && (
        <label
          htmlFor={id}
          className={`absolute left-3 -top-2.5 px-2 text-xs transition-all 
            peer-placeholder-shown:top-2.5 peer-placeholder-shown:left-3 peer-placeholder-shown:text-base 
            peer-placeholder-shown:text-gray-4000 peer-focus:-top-2.5 peer-focus:left-3 peer-focus:text-xs 
            peer-focus:text-gray-4000 dark:text-silver dark:peer-placeholder-shown:text-gray-400 
            cursor-none pointer-events-none ${labelBgClassName}`}
        >
          {placeholder}
          {required && (
            <span className="text-[#D30000] dark:text-[#D42626] ml-0.5">*</span>
          )}
        </label>
      )}
    </div>
  );
};

export default Input;
