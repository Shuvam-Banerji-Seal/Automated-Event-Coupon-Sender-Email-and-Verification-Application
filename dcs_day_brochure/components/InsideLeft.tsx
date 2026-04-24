import React from 'react';
import { BrochurePage } from './BrochurePage';
import { RESEARCH_AREAS, ORGANIZERS } from '../constants';
import { HexagonPattern } from './Decorations';

export const InsideLeft: React.FC = () => {
  const pgac = ORGANIZERS.find(o => o.role === 'PGAC Convenor')?.name;
  const ugac = ORGANIZERS.find(o => o.role === 'UGAC Convenor')?.name;

  return (
    <BrochurePage className="bg-slate-50 text-gray-800 p-8 relative overflow-hidden">
      
      <HexagonPattern className="text-gray-200" opacity={0.3} />

      <div className="relative z-10 flex flex-col h-full">
        {/* Header */}
        <div className="mb-8">
          <h2 className="text-2xl font-serif font-bold text-dcs-green mb-2">About The Department</h2>
          <div className="h-1 w-16 bg-dcs-blue rounded-full"></div>
        </div>

        {/* About Content */}
        <div className="space-y-4 text-justify text-sm leading-relaxed font-sans mb-8">
          <p>
            The Department of Chemical Sciences (DCS) at IISER Kolkata is a vibrant center for 
            teaching and research. Since its inception, DCS has been committed to excellence in 
            chemical education and research, fostering an environment where innovation thrives.
          </p>
          <p>
            Led by our Head of Department, <span className="font-bold text-dcs-blue">Prof. Debasish Haldar</span>, 
            along with PGAC Convenor <span className="font-bold text-dcs-blue">{pgac}</span> and 
            UGAC Convenor <span className="font-bold text-dcs-blue">{ugac}</span>,
            the department boasts a diverse and accomplished faculty working at the frontiers of 
            chemical sciences. DCS Day is our annual celebration of this spirit of inquiry and 
            scientific community.
          </p>
        </div>

        {/* Research Highlights */}
        <div className="flex-1">
          <h3 className="text-xl font-serif font-bold text-dcs-blue mb-4 flex items-center">
            <span className="bg-dcs-blue text-white w-6 h-6 rounded-full flex items-center justify-center text-xs mr-2">R</span>
            Research Focus
          </h3>
          
          <div className="grid grid-cols-1 gap-4">
            {RESEARCH_AREAS.map((area, index) => (
              <div key={index} className="bg-white/80 backdrop-blur-sm p-4 rounded-lg shadow-sm border border-slate-200">
                <h4 className="font-bold text-dcs-green text-sm mb-2 uppercase tracking-wide">{area.title}</h4>
                <div className="flex flex-wrap gap-2">
                  {area.topics.map((topic, i) => (
                    <span key={i} className="text-xs bg-slate-100 text-slate-600 px-2 py-1 rounded-md">
                      {topic}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
        
         <div className="mt-8 pt-4 border-t border-gray-200">
           <p className="text-xs text-center text-gray-400 italic">
             Exploring the molecular world to solve global challenges.
           </p>
         </div>
      </div>
    </BrochurePage>
  );
};