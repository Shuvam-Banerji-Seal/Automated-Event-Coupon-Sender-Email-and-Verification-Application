import React, { useState } from 'react';
import { FrontCover } from './components/FrontCover';
import { InsideLeft } from './components/InsideLeft';
import { InsideRight } from './components/InsideRight';
import { BackCover } from './components/BackCover';

// Declare html2pdf for TypeScript since it's loaded via CDN
declare var html2pdf: any;

function App() {
  const [isGenerating, setIsGenerating] = useState(false);

  const handlePrint = () => {
    window.print();
  };

  const handleDownloadPdf = () => {
    const element = document.getElementById('brochure-content');
    if (!element) return;

    setIsGenerating(true);

    // Options for A5 PDF
    const opt = {
      margin: 0,
      filename: 'DCS_Day_26_Brochure.pdf',
      image: { type: 'jpeg', quality: 0.98 },
      html2canvas: { 
        scale: 2, // Higher scale for better resolution
        useCORS: true, // Crucial for loading images from GitHub
        scrollY: 0,
      },
      jsPDF: { unit: 'mm', format: 'a5', orientation: 'portrait' }
    };

    // Add class for styling overrides during capture
    element.classList.add('pdf-generating');

    html2pdf()
      .from(element)
      .set(opt)
      .save()
      .then(() => {
        element.classList.remove('pdf-generating');
        setIsGenerating(false);
      })
      .catch((err: any) => {
        console.error("PDF Generation failed", err);
        element.classList.remove('pdf-generating');
        setIsGenerating(false);
      });
  };

  return (
    <div className="min-h-screen bg-gray-200 py-8 print:bg-white print:py-0">
      
      {/* Controls - Hidden on Print */}
      <div className="fixed top-4 right-4 z-50 print:hidden space-y-2">
        <div className="bg-white p-4 rounded-lg shadow-lg max-w-xs">
          <h3 className="font-bold text-gray-800 mb-2">Printing Instructions</h3>
          <ul className="text-xs text-gray-600 list-disc pl-4 mb-4 space-y-1">
            <li>Paper Size: <strong>A5</strong></li>
            <li>Orientation: <strong>Portrait</strong></li>
            <li>Margins: <strong>None / Minimum</strong></li>
            <li>Enable <strong>Background Graphics</strong></li>
          </ul>
          
          <div className="flex flex-col gap-2">
            <button 
              onClick={handleDownloadPdf}
              disabled={isGenerating}
              className={`w-full ${isGenerating ? 'bg-gray-400' : 'bg-dcs-green hover:bg-green-800'} text-white font-bold py-2 px-4 rounded transition-colors flex items-center justify-center gap-2`}
            >
               {isGenerating ? (
                 <span>Generating...</span>
               ) : (
                 <>
                  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-5 h-5">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3" />
                  </svg>
                  Download PDF
                 </>
               )}
            </button>

            <button 
              onClick={handlePrint}
              className="w-full bg-blue-600 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded transition-colors flex items-center justify-center gap-2"
            >
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-5 h-5">
                <path strokeLinecap="round" strokeLinejoin="round" d="M6.72 13.829c-.24.03-.48.062-.72.096m.72-.096a42.415 42.415 0 0110.56 0m-10.56 0L6.34 18m10.94-4.171c.24.03.48.062.72.096m-.72-.096L17.66 18m0 0l.229 2.523a1.125 1.125 0 01-1.12 1.227H7.231c-.662 0-1.18-.568-1.12-1.227L6.34 18m11.318 0h1.091A2.25 2.25 0 0021 15.75V9.456c0-1.081-.768-2.015-1.837-2.175a48.055 48.055 0 00-1.913-.247M6.34 18H5.25A2.25 2.25 0 013 15.75V9.456c0-1.081.768-2.015 1.837-2.175a48.041 48.041 0 011.913-.247m10.5 0a48.536 48.536 0 00-10.5 0m10.5 0V3.375c0-.621-.504-1.125-1.125-1.125h-8.25c-.621 0-1.125.504-1.125 1.125v3.659M18 10.5h.008v.008H18V10.5zm-3 0h.008v.008H15V10.5z" />
              </svg>
              Print / Save PDF
            </button>
          </div>
        </div>
      </div>

      {/* Brochure Container - Target for html2pdf */}
      <div id="brochure-content" className="flex flex-col gap-8 print:gap-0 items-center">
        {/* Front Cover */}
        <div className="shadow-2xl print:shadow-none print:break-after-page">
           <FrontCover />
        </div>

        {/* Inside Spread (Left & Right) - Displayed as spread on screen, pages in print */}
        <div className="flex flex-col md:flex-row gap-0 shadow-2xl print:shadow-none print:block print:w-full">
           <div className="print:break-after-page">
              <InsideLeft />
           </div>
           <div className="print:break-after-page">
              <InsideRight />
           </div>
        </div>

        {/* Back Cover */}
        <div className="shadow-2xl print:shadow-none">
           <BackCover />
        </div>
      </div>

    </div>
  );
}

export default App;