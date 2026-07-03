'use client';
import React, { useState } from 'react';
import {
  ShieldCheck, FileText, Cpu, XCircle, AlertTriangle, ChevronDown, ChevronRight,
  DollarSign, BarChart2
} from 'lucide-react';
import type { TransparencyReport } from '../lib/types';

interface Props {
  report: TransparencyReport;
}

function Section({ title, icon, children, defaultOpen = false }: {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border border-white/10 rounded-xl overflow-hidden">
      <button
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-white/5 transition-colors text-left"
        onClick={() => setOpen(!open)}
        id={`transparency-${title.replace(/\s+/g, '-').toLowerCase()}`}
      >
        <span className="text-brand-400">{icon}</span>
        <span className="text-sm font-medium text-slate-200 flex-1">{title}</span>
        {open ? <ChevronDown className="w-4 h-4 text-slate-500" /> : <ChevronRight className="w-4 h-4 text-slate-500" />}
      </button>
      {open && (
        <div className="px-4 pb-4 pt-2 border-t border-white/10 animate-fade-in">
          {children}
        </div>
      )}
    </div>
  );
}

export default function TransparencyReport({ report }: Props) {
  const { llm_usage } = report;

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center gap-2 mb-4 flex-shrink-0">
        <ShieldCheck className="w-5 h-5 text-emerald-400" />
        <h2 className="text-lg font-semibold text-white">Transparency Report</h2>
      </div>

      <div className="flex-1 overflow-y-auto space-y-2 pr-1">
        {/* Summary stats */}
        <Section title="Summary" icon={<BarChart2 className="w-4 h-4" />} defaultOpen>
          <div className="grid grid-cols-2 gap-2 mt-2">
            {[
              { label: 'Papers analyzed', value: report.papers_analyzed, color: 'text-brand-400' },
              { label: 'Claims extracted', value: report.claims_extracted, color: 'text-violet-400' },
              { label: 'Sentences generated', value: report.sentences_generated, color: 'text-slate-300' },
              { label: 'Verified ✓', value: report.sentences_verified, color: 'text-emerald-400' },
              { label: 'Rejected ✗', value: report.sentences_rejected, color: 'text-red-400' },
              { label: 'Open questions', value: report.open_clarifications, color: 'text-amber-400' },
            ].map(({ label, value, color }) => (
              <div key={label} className="bg-white/5 rounded-lg px-3 py-2">
                <p className={`text-lg font-bold ${color}`}>{value}</p>
                <p className="text-xs text-slate-500">{label}</p>
              </div>
            ))}
          </div>
        </Section>

        {/* Rejected sentences */}
        {report.rejected_details.length > 0 && (
          <Section
            title={`Rejected Sentences (${report.rejected_details.length})`}
            icon={<XCircle className="w-4 h-4" />}
          >
            <div className="space-y-2 mt-2 max-h-60 overflow-y-auto">
              {report.rejected_details.map(item => (
                <div key={item.id} className="px-3 py-2 rounded-lg bg-red-500/5 border border-red-500/20 space-y-1">
                  <p className="text-xs text-slate-400 line-clamp-2">{item.text}</p>
                  <p className="text-xs text-red-400">
                    <span className="font-medium">Reason: </span>
                    {item.rejection_reason}
                  </p>
                  <span className="badge badge-pending text-slate-500">
                    Section: {item.section}
                  </span>
                </div>
              ))}
            </div>
          </Section>
        )}

        {/* LLM usage */}
        <Section title="API Usage & Estimated Cost" icon={<DollarSign className="w-4 h-4" />}>
          <div className="mt-2 space-y-2">
            <div className="flex justify-between text-sm">
              <span className="text-slate-400">Total tokens used</span>
              <span className="text-slate-200 font-mono">
                {(llm_usage.total_prompt_tokens + llm_usage.total_completion_tokens).toLocaleString()}
              </span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-slate-400">Estimated cost</span>
              <span className="text-emerald-400 font-mono font-semibold">
                ${llm_usage.total_cost_usd.toFixed(4)} USD
              </span>
            </div>
            <div className="border-t border-white/10 pt-2 mt-2 space-y-1">
              {Object.entries(llm_usage.by_stage || {}).map(([stage, usage]) => (
                <div key={stage} className="flex items-center justify-between text-xs">
                  <span className="text-slate-500 font-mono">{stage}</span>
                  <span className="text-slate-500">{usage.model}</span>
                  <span className="text-slate-400">${usage.cost_usd.toFixed(5)}</span>
                </div>
              ))}
            </div>
          </div>
        </Section>

        {/* How it works note */}
        <Section title="How citations are verified" icon={<Cpu className="w-4 h-4" />}>
          <div className="mt-2 space-y-2 text-xs text-slate-400 leading-relaxed">
            <p>
              <span className="text-brand-400 font-medium">Writing:</span> Claude (Sonnet) drafted each sentence
              and included a reference to the source claim it drew from.
            </p>
            <p>
              <span className="text-emerald-400 font-medium">Checking:</span> GPT-4o-mini independently verified
              that each cited source actually supports the sentence. These are two different AI systems checking
              each other's work.
            </p>
            <p>
              <span className="text-red-400 font-medium">Rejection:</span> Any sentence that failed the check
              was dropped entirely — not reworded or kept.
            </p>
          </div>
        </Section>
      </div>
    </div>
  );
}
