import React from 'react';

interface BrochurePageProps {
  children: React.ReactNode;
  className?: string;
}

export const BrochurePage: React.FC<BrochurePageProps> = ({ children, className = '' }) => {
  return (
    <div className={`a5-page relative flex flex-col ${className}`}>
      {children}
    </div>
  );
};