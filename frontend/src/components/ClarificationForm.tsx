'use client';
import React, { useState } from 'react';
import { MessageSquare, CheckCircle, Send } from 'lucide-react';
import { submitClarification } from '../lib/api';
import type { ClarificationRequest } from '../lib/types';

interface Props {
  clarifications: ClarificationRequest[];
  onResolved: () => void;
}

const FIELD_LABELS: Record<string, string> = {
  problem_statement: 'Problem Statement',
  methodology: 'Methodology',
  results: 'Results & Outcomes',
  title: 'Project Title',
};

export default function ClarificationForm({ clarifications, onResolved }: Props) {
  const [responses, setResponses] = useState<Record<number, string>>({});
  const [submitting, setSubmitting] = useState<Record<number, boolean>>({});
  const [resolved, setResolved] = useState<Set<number>>(new Set());

  const unresolved = clarifications.filter(c => !resolved.has(c.id) && !c.resolved);

  if (!unresolved.length) return null;

  const handleSubmit = async (clarification: ClarificationRequest) => {
    const response = responses[clarification.id]?.trim();
    if (!response) return;
    setSubmitting(prev => ({ ...prev, [clarification.id]: true }));
    try {
      await submitClarification(clarification.id, response);
      setResolved(prev => new Set([...prev, clarification.id]));
      onResolved();
    } catch (err) {
      console.error('Failed to submit clarification:', err);
    } finally {
      setSubmitting(prev => ({ ...prev, [clarification.id]: false }));
    }
  };

  const allAnswered = unresolved.every(c => responses[c.id]?.trim());

  return (
    <div className="space-y-4 animate-slide-up">
      <div className="flex items-center gap-2">
        <div className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
        <h3 className="text-sm font-semibold text-amber-400">
          A few things need your input ({unresolved.length})
        </h3>
      </div>
      <p className="text-xs text-slate-500">
        These fields couldn't be found automatically in your project file.
        Fill them in to improve your paper — the pipeline will use your answers.
      </p>

      <div className="space-y-3">
        {unresolved.map(c => {
          const isResolved = resolved.has(c.id);
          const label = FIELD_LABELS[c.field_name] || c.field_name;
          return (
            <div
              key={c.id}
              className={`card p-4 space-y-3 transition-all duration-300
                ${isResolved ? 'opacity-50' : ''}`}
            >
              <div className="flex items-start gap-2">
                <MessageSquare className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
                <div>
                  <p className="text-xs font-semibold text-amber-400 uppercase tracking-wide">{label}</p>
                  <p className="text-sm text-slate-300 mt-0.5">{c.prompt}</p>
                </div>
              </div>
              {isResolved ? (
                <div className="flex items-center gap-2 text-xs text-emerald-400">
                  <CheckCircle className="w-3.5 h-3.5" />
                  Saved
                </div>
              ) : (
                <div className="flex gap-2">
                  <textarea
                    id={`clarification-${c.id}`}
                    className="input-field text-sm resize-none flex-1"
                    rows={3}
                    placeholder="Your answer..."
                    value={responses[c.id] || ''}
                    onChange={e => setResponses(prev => ({ ...prev, [c.id]: e.target.value }))}
                    onKeyDown={e => {
                      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit(c);
                    }}
                  />
                  <button
                    onClick={() => handleSubmit(c)}
                    disabled={!responses[c.id]?.trim() || submitting[c.id]}
                    className="btn-secondary self-end flex-shrink-0 py-2 px-3"
                    title="Save (Ctrl+Enter)"
                  >
                    {submitting[c.id]
                      ? <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
                      : <Send className="w-4 h-4" />}
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
