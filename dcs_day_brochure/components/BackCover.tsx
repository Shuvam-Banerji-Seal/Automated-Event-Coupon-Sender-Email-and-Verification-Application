import React from 'react';
import { BrochurePage } from './BrochurePage';
import { ORGANIZERS, CONTACTS, LOGOS, SPONSORSHIP } from '../constants';
import { HexagonPattern } from './Decorations';

export const BackCover: React.FC = () => {
  return (
    <BrochurePage className="bg-dcs-dark text-white p-8 flex flex-col relative border-l border-gray-800 print:border-none overflow-hidden">
      
      {/* Background Decor */}
      {/* Increased pattern opacity slightly to be visible through blur */}
      <HexagonPattern className="text-gray-600" opacity={0.2} />
      
      {/* Blur Overlay - Sits above SVG (z-0) but below content (z-10) */}
      <div className="absolute inset-0 bg-dcs-dark/60 backdrop-blur-[3px] z-0 pointer-events-none"></div>
      
      {/* Top Graphic */}
      <div className="absolute top-0 left-0 w-full h-2 bg-gradient-to-r from-dcs-green to-dcs-blue z-20"></div>

      {/* Main Content - Aligned to Top */}
      <div className="flex-1 flex flex-col justify-start gap-8 mt-8 z-10 relative">
        
        {/* Organizers */}
        <div className="w-full">
          <h3 className="text-lg font-serif font-bold text-white mb-6 uppercase tracking-widest text-center border-b border-gray-700 pb-2 inline-block relative left-1/2 transform -translate-x-1/2 px-8 shadow-black drop-shadow-md">
            Organizing Committee
          </h3>
          
          <div className="grid grid-cols-2 gap-4">
            <div className="text-center border-r border-gray-700 pr-4">
               {/* Enhanced Header: Brighter Green, Extrabold, Glow Effect */}
               <h4 className="text-green-400 font-extrabold text-xs uppercase mb-2 tracking-widest drop-shadow-[0_0_10px_rgba(74,222,128,0.5)]">
                 Event In-Charge (Faculty)
               </h4>
               <ul className="space-y-1 text-xs font-light text-gray-200">
                 {ORGANIZERS.filter(o => o.role === 'Event In-Charge (Faculty)').map((org, i) => (
                   <li key={i}>{org.name}</li>
                 ))}
               </ul>
            </div>
            
            <div className="text-center pl-4 flex flex-col justify-start">
               {/* Enhanced Header: Brighter Green, Extrabold, Glow Effect */}
               <h4 className="text-green-400 font-extrabold text-xs uppercase mb-2 tracking-widest drop-shadow-[0_0_10px_rgba(74,222,128,0.5)]">
                 Student In-Charge
               </h4>
               <p className="text-xs font-light text-gray-200">
                 {ORGANIZERS.find(o => o.role === 'Student In-Charge')?.name}
               </p>
               <p className="text-[10px] text-gray-400 mt-1">
                  {ORGANIZERS.find(o => o.role === 'Student In-Charge')?.contact}
               </p>
            </div>
          </div>
        </div>

        {/* Sponsorship & Payment */}
        <div className="bg-white text-dcs-dark p-4 rounded-lg shadow-2xl flex flex-row gap-4 items-center relative overflow-hidden ring-1 ring-gray-900/5">
          <div className="absolute top-0 right-0 w-16 h-16 bg-dcs-green/5 rounded-bl-full -mr-8 -mt-8 pointer-events-none"></div>
          
          <div className="flex-1 z-10">
            <h4 className="font-serif text-base font-bold text-dcs-green mb-1">Sponsorship Facilities</h4>
            <p className="text-[10px] font-bold text-gray-600 mb-2">Minimum Sponsorship: ₹{SPONSORSHIP.minAmount}</p>
            <ul className="list-disc pl-3 text-[10px] text-gray-700 space-y-1 leading-tight">
              {SPONSORSHIP.facilities.map((fac, i) => <li key={i}>{fac}</li>)}
            </ul>
             <p className="text-[9px] text-gray-500 mt-2 italic">
              Please mail the payment receipt with logo and info to <span className="font-bold">{SPONSORSHIP.contactEmail}</span>
            </p>
          </div>
          <div className="flex flex-col items-center justify-center flex-shrink-0 bg-gray-50 p-2 rounded border border-gray-200 z-10 shadow-inner">
             <img src={SPONSORSHIP.qrCodeUrl} alt="UPI QR Code" className="w-20 h-20 mix-blend-multiply" />
             <p className="text-[9px] font-mono mt-1 text-gray-600">Scan to Pay</p>
          </div>
        </div>
      </div>

      {/* Footer / Contact Details */}
      <div className="text-center space-y-2 mt-auto pt-4 z-10 relative">
        <div className="w-12 h-0.5 bg-gray-600 mx-auto mb-2"></div>
        
        <div className="text-xs text-gray-400 font-sans space-y-2">
          <div>
             <span className="text-gray-200 font-bold block">Office Staff & General Enquiries</span>
             <p>{CONTACTS.officeStaff}</p>
             <p>Department Office: {CONTACTS.officeEmail}</p>
          </div>
          
          <div>
            <span className="text-gray-200 font-bold block mb-1">Student Representatives</span>
            <div className="flex justify-center flex-wrap gap-x-4 gap-y-1">
              {CONTACTS.studentReps.map((rep, idx) => (
                <div key={idx} className="flex flex-col items-center mx-2">
                  <span className="text-gray-300 font-semibold">{rep.name}</span>
                  <span className="text-[10px] text-gray-400">{rep.email}</span>
                  <span className="text-[10px] opacity-75">{rep.phone}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="pt-4 mt-2 border-t border-gray-800 flex justify-center space-x-4 opacity-50 grayscale hover:grayscale-0 transition-all">
           <img src={LOGOS.DCS_GREEN} className="h-6 bg-white rounded p-0.5" alt="DCS Logo" />
           <img src={LOGOS.IISER} className="h-6 bg-white rounded p-0.5" alt="IISER Logo" />
        </div>
        
        <div className="text-[9px] text-gray-600 uppercase tracking-widest mt-2">
          Mohanpur, Nadia - 741246, West Bengal
        </div>
      </div>
    </BrochurePage>
  );
};