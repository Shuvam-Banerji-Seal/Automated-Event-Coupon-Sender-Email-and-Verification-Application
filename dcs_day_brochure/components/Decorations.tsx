import React from 'react';

export const HexagonPattern: React.FC<{ className?: string; opacity?: number }> = ({ className = "", opacity = 0.1 }) => (
  <svg className={`absolute inset-0 w-full h-full pointer-events-none ${className}`} xmlns="http://www.w3.org/2000/svg">
    <defs>
      <pattern id="hexagons" width="50" height="43.4" patternUnits="userSpaceOnUse" patternTransform="scale(0.8)">
        <path d="M25 0 L50 14.4 L50 43.3 L25 57.7 L0 43.3 L0 14.4 Z" fill="none" stroke="currentColor" strokeWidth="1" opacity={opacity} />
      </pattern>
    </defs>
    <rect width="100%" height="100%" fill="url(#hexagons)" />
  </svg>
);

export const MoleculeAccent: React.FC<{ className?: string }> = ({ className = "" }) => (
  <svg className={className} viewBox="0 0 100 100" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M50 20 L76 35 L76 65 L50 80 L24 65 L24 35 Z" />
    <circle cx="50" cy="50" r="15" />
    <path d="M50 20 L50 5" />
    <path d="M76 35 L89 27.5" />
    <path d="M76 65 L89 72.5" />
    <path d="M24 65 L11 72.5" />
    <path d="M24 35 L11 27.5" />
    <circle cx="50" cy="5" r="3" fill="currentColor" stroke="none" />
    <circle cx="89" cy="27.5" r="3" fill="currentColor" stroke="none" />
    <circle cx="89" cy="72.5" r="3" fill="currentColor" stroke="none" />
    <circle cx="11" cy="72.5" r="3" fill="currentColor" stroke="none" />
    <circle cx="11" cy="27.5" r="3" fill="currentColor" stroke="none" />
  </svg>
);
