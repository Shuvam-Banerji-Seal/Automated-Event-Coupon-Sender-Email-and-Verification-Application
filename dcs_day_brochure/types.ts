import React from 'react';

export interface Guest {
  name: string;
  title: string;
  affiliation: string;
  role: 'External Guest' | 'Faculty' | 'Speaker';
}

export interface Organizer {
  name: string;
  role: string;
  contact?: string;
  email?: string;
}

export interface EventHighlight {
  title: string;
  description: string;
  icon: React.ReactNode;
}

export interface ResearchArea {
  title: string;
  topics: string[];
}