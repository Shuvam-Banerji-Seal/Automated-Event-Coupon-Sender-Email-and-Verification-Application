import React from 'react';
import { BrochurePage } from './BrochurePage';
import { EXTERNAL_GUESTS, INTERNAL_SPEAKERS, HIGHLIGHTS } from '../constants';
import { HexagonPattern } from './Decorations';

export const InsideRight: React.FC = () => {
  return (
    <BrochurePage className="bg-white text-gray-800 p-8 relative overflow-hidden">
      
       <HexagonPattern className="text-slate-100" opacity={0.6} />

       <div className="relative z-10 flex flex-col h-full">
         {/* Event Highlights Header */}
         <div className="mb-4 flex items-center justify-between">
          <div>
             <h2 className="text-2xl font-serif font-bold text-dcs-blue mb-1">Event Highlights</h2>
             <div className="h-1 w-16 bg-dcs-green rounded-full"></div>
          </div>
          <div className="text-right">
               <span className="text-xs font-bold text-dcs-green bg-green-50 px-2 py-1 rounded border border-green-100">
                  Full Day Event
               </span>
          </div>
        </div>

        {/* Highlights Grid */}
        <div className="grid grid-cols-2 gap-3 mb-6">
          {HIGHLIGHTS.map((item, idx) => (
            <div key={idx} className="flex flex-col items-start p-2.5 bg-slate-50/90 backdrop-blur-sm rounded-lg border-l-4 border-dcs-green shadow-sm">
              <div className="text-dcs-blue mb-1">
                {item.icon}
              </div>
              <h4 className="font-bold text-sm mb-0.5">{item.title}</h4>
              <p className="text-[10px] text-gray-600 leading-snug">{item.description}</p>
            </div>
          ))}
        </div>

        {/* Guest Speakers Section */}
        <div className="flex-1 flex flex-col gap-4">
          <div>
              <h3 className="text-lg font-serif font-bold text-dcs-green mb-3 border-b border-gray-100 pb-1">
                Distinguished Guest Speakers
              </h3>
              
              <div className="grid grid-cols-1 gap-3">
                {EXTERNAL_GUESTS.map((guest, index) => (
                  <div key={index} className="flex items-start space-x-3">
                    <div className="flex-shrink-0 w-8 h-8 rounded-full bg-dcs-blue text-white flex items-center justify-center font-serif font-bold text-sm shadow-sm">
                      {guest.name.charAt(0)}
                    </div>
                    <div>
                      <h4 className="font-bold text-gray-900 text-sm">{guest.name}</h4>
                      <p className="text-[10px] text-dcs-green font-semibold uppercase tracking-wide leading-tight">{guest.title}</p>
                      <p className="text-[11px] text-gray-500 italic leading-tight">{guest.affiliation}</p>
                    </div>
                  </div>
                ))}
              </div>
          </div>

          <div>
              <h3 className="text-lg font-serif font-bold text-dcs-blue mb-3 border-b border-gray-100 pb-1">
                Institute Speakers
              </h3>
              
              <div className="grid grid-cols-1 gap-2">
                {INTERNAL_SPEAKERS.map((guest, index) => (
                  <div key={index} className="flex items-center space-x-3">
                     <div className="w-1.5 h-1.5 bg-dcs-green rounded-full"></div>
                     <div className="flex-1 flex justify-between items-baseline border-b border-dashed border-gray-100 pb-1">
                        <span className="font-bold text-gray-800 text-sm">{guest.name}</span>
                        <span className="text-[10px] text-gray-500 italic">{guest.title}</span>
                     </div>
                  </div>
                ))}
              </div>
          </div>
        </div>

        <div className="mt-4 p-3 bg-yellow-50/90 backdrop-blur-sm rounded-lg border border-yellow-100">
          <p className="text-center text-[10px] text-yellow-800 font-semibold uppercase tracking-wide">
            Lunch • High Tea • Conference Goodies Provided
          </p>
        </div>
      </div>

    </BrochurePage>
  );
};