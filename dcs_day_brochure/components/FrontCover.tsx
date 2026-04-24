import React from 'react';
import { BrochurePage } from './BrochurePage';
import { LOGOS } from '../constants';
import { HexagonPattern, MoleculeAccent } from './Decorations';

export const FrontCover: React.FC = () => {
  return (
    <BrochurePage className="bg-white text-dcs-dark border-r border-gray-200 print:border-none relative overflow-hidden">
      
      {/* Background Decor */}
      <HexagonPattern className="text-gray-100" opacity={0.4} />
      <div className="absolute top-0 right-0 w-32 h-32 bg-dcs-green/10 rounded-bl-full z-0"></div>
      <div className="absolute bottom-0 left-0 w-48 h-48 bg-dcs-blue/10 rounded-tr-full z-0"></div>
      
      {/* Molecule Accent */}
      <MoleculeAccent className="absolute top-1/3 right-8 w-24 h-24 text-dcs-green/10 transform rotate-12 z-0" />

      <div className="flex-1 flex flex-col items-center justify-between p-12 z-10">
        
        {/* Logos Header */}
        <div className="w-full flex justify-between items-start">
           <img 
            src={LOGOS.IISER} 
            alt="IISER Kolkata Logo" 
            className="h-20 object-contain"
          />
           <img 
            src={LOGOS.DCS_BLUE} 
            alt="DCS Logo" 
            className="h-20 object-contain"
          />
        </div>

        {/* Main Title Section */}
        <div className="text-center space-y-6">
          <div className="inline-block border-b-4 border-dcs-green pb-2 mb-4 bg-white/50 backdrop-blur-sm p-2 rounded">
             <span className="text-xl tracking-[0.2em] uppercase font-sans text-gray-500">Department of Chemical Sciences</span>
          </div>
          
          <h1 className="text-6xl font-serif font-bold text-dcs-blue leading-tight relative">
            DCS Day <span className="text-dcs-green">'26</span>
          </h1>
          
          <p className="text-xl font-sans font-light italic text-gray-600 max-w-xs mx-auto">
            Celebrating the Foundation of Our Department
          </p>
        </div>

        {/* Date & Location */}
        <div className="text-center space-y-2 bg-white/80 p-4 rounded-xl backdrop-blur-sm shadow-sm border border-gray-100">
            <div className="text-3xl font-serif font-bold text-dcs-dark">
              January 28, 2026
            </div>
            <div className="text-sm font-sans uppercase tracking-widest text-gray-500">
              IISER Kolkata
            </div>
        </div>

         {/* Footer Strip */}
        <div className="w-full border-t border-gray-300 pt-6 flex flex-col items-center">
             <p className="text-xs text-gray-400 font-sans tracking-widest text-center bg-white px-2">
                INNOVATION • DISCOVERY • EXCELLENCE
             </p>
        </div>
      </div>
    </BrochurePage>
  );
};