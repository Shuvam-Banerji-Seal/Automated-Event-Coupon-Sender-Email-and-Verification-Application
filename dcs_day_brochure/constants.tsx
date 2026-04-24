import React from 'react';
import { Guest, Organizer, ResearchArea, EventHighlight } from './types';

// Icons
const PresentationChartBarIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-6 h-6">
    <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 3v11.25A2.25 2.25 0 006 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0118 16.5h-2.25m-7.5 0h7.5m-7.5 0l-1 3m8.5-3l1 3m0 0l.5 1.5m-.5-1.5h-9.5m0 0l-.5 1.5m.75-9l3-3 2.148 2.148A12.061 12.061 0 0116.5 7.605" />
  </svg>
);

const VideoCameraIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-6 h-6">
    <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 10.5l4.72-4.72a.75.75 0 011.28.53v11.38a.75.75 0 01-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 002.25-2.25v-9a2.25 2.25 0 00-2.25-2.25h-9A2.25 2.25 0 002.25 7.5v9a2.25 2.25 0 002.25 2.25z" />
  </svg>
);

const SparklesIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-6 h-6">
    <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z" />
  </svg>
);

const UserGroupIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-6 h-6">
    <path strokeLinecap="round" strokeLinejoin="round" d="M18 18.72a9.094 9.094 0 003.741-.479 3 3 0 00-4.682-2.72m.94 3.198l.001.031c0 .225-.012.447-.037.666A11.944 11.944 0 0112 21c-2.17 0-4.207-.576-5.963-1.584A6.062 6.062 0 016 18.719m12 0a5.971 5.971 0 00-.941-3.197m0 0A5.995 5.995 0 0012 12.75a5.995 5.995 0 00-5.058 5.472m0 0a9.09 9.09 0 00-3.279 3.298m.944-5.463A6.001 6.001 0 0112 11.25a6.001 6.001 0 004.978 5.434M12 11.25a5.25 5.25 0 100-10.5 5.25 5.25 0 000 10.5z" />
  </svg>
);

export const EXTERNAL_GUESTS: Guest[] = [
  {
    name: 'Dr. Satyadeep Waiba',
    title: 'Assistant Professor',
    affiliation: 'IIT Bombay',
    role: 'External Guest',
  },
  {
    name: 'Dr. Arpita Paikar',
    title: 'Scientist, FTSI',
    affiliation: 'TCG Crest, Kolkata',
    role: 'External Guest',
  },
  {
    name: 'Prof. Souvik Maiti',
    title: 'Professor',
    affiliation: 'IGIB, Delhi',
    role: 'External Guest',
  },
];

export const INTERNAL_SPEAKERS: Guest[] = [
  {
    name: 'Dr. Biplab Maji',
    title: 'Associate Professor',
    affiliation: 'IISER Kolkata',
    role: 'Speaker',
  },
  {
    name: 'Dr. Dibyendu Das',
    title: 'Professor',
    affiliation: 'IISER Kolkata',
    role: 'Speaker',
  },
  {
    name: 'Dr. Susmita Roy',
    title: 'Assistant Professor',
    affiliation: 'IISER Kolkata',
    role: 'Speaker',
  },
];

export const ORGANIZERS: Organizer[] = [
  { name: 'Prof. Sangita Sen', role: 'Event In-Charge (Faculty)' },
  { name: 'Prof. Supratim Banerjee', role: 'Event In-Charge (Faculty)' },
  { name: 'Prof. Sumit Khanra', role: 'Event In-Charge (Faculty)' },
  { name: 'Prof. Pradip Kumar Tarafdar', role: 'PGAC Convenor' },
  { name: 'Prof. Supratim Banerjee', role: 'UGAC Convenor' },
  { name: 'Mr. Sanu Sar', role: 'Student In-Charge', contact: '+91 7003813228', email: 'ss21rs106@iiserkol.ac.in' },
];

export const CONTACTS = {
  studentReps: [
    { name: 'Sanu Sar', email: 'ss21rs106@iiserkol.ac.in', phone: '+91 7003813228' },
    { name: 'Jesslyn John P', email: 'jjp23rs046@iiserkol.ac.in', phone: '+91 90721 72364' }
  ],
  officeStaff: 'Mr. Rangan Bhattacharya (rangan.b@iiserkol.ac.in)',
  officeEmail: 'dcs.office@iiserkol.ac.in'
};

export const SPONSORSHIP = {
  minAmount: '20,000',
  upiId: 'sanusar1232@oksbi',
  contactEmail: 'ss21rs106@iiserkol.ac.in',
  qrCodeUrl: 'https://api.qrserver.com/v1/create-qr-code/?size=150x150&data=upi%3A%2F%2Fpay%3Fpa%3Dsanusar1232%40oksbi%26pn%3DSanu%2520Sar%26cu%3DINR',
  facilities: [
    'Sponsored companies will be highlighted in the posters, flex, and slides.',
    '1 Company staff will be invited for the whole day (Lunch, snacks, and dinner provided).'
  ]
};

export const HIGHLIGHTS: EventHighlight[] = [
  {
    title: 'Inaugural & Lectures',
    description: 'Keynote addresses by distinguished guest speakers from premier institutes.',
    icon: <UserGroupIcon />,
  },
  {
    title: 'Research Showcase',
    description: 'Oral presentations by faculty and scholars featuring cutting-edge discoveries.',
    icon: <PresentationChartBarIcon />,
  },
  {
    title: 'Lab Visits',
    description: 'Special allowance for physical lab visits for the day, alongside recorded video presentations.',
    icon: <VideoCameraIcon />,
  },
  {
    title: 'Cultural Evening',
    description: 'A vibrant cultural program followed by a community dinner.',
    icon: <SparklesIcon />,
  },
];

export const RESEARCH_AREAS: ResearchArea[] = [
  {
    title: 'Material Science',
    topics: ['Piezoelectric Bioisosteres', 'TADF Emitters', 'Energy Nexus'],
  },
  {
    title: 'Chemical Biology',
    topics: ['Nucleic Acid Folding', 'Cancer Therapeutics', 'Chemo-Photodynamic Therapy'],
  },
  {
    title: 'Synthetic Chemistry',
    topics: ['Supramolecular Assemblies', 'Photoreaction Control', 'Polymer Architecture'],
  },
  {
    title: 'Physical Chemistry',
    topics: ['Quantum Dynamics', 'Micro Bubble Lithography', 'Excited State Dynamics'],
  },
];

export const LOGOS = {
  DCS_GREEN: 'https://raw.githubusercontent.com/Shuvam-Banerji-Seal/Email-HTML/refs/heads/main/assets/DCS-logo-green.jpg',
  DCS_BLUE: 'https://raw.githubusercontent.com/Shuvam-Banerji-Seal/Email-HTML/refs/heads/main/assets/DCS_logo_blue.jpg',
  IISER: 'https://upload.wikimedia.org/wikipedia/en/b/b3/IISER_Kolkata_Logo.png',
};
