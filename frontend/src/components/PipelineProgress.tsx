'use client';
import React from 'react';
import { CheckCircle, Loader2, Clock, AlertCircle } from 'lucide-react';
import type { PipelineEvent } from '../lib/types';

interface Props {
  events: PipelineEvent[];
  isRunning: boolean;
  hasError: boolean;
  errorMsg?: string;
}

const STAGE_LABELS = [
  'Files ready',
  'Extracting papers',
  'Building knowledge store',
  'Analyzing project',
  'Comparing with literature',
  'Generating & verifying paper',
  'Output ready',
];

export default function PipelineProgress({ events, isRunning, hasError, errorMsg }: Props) {
  const latestStageEvent = [...events].reverse().find(e => e.stage !== undefined);
  const currentStage = latestStageEvent?.stage ?? 0;
  const latestMessage = latestStageEvent?.message ?? '';
  const isDone = events.some(e => e.done);

  const progress = isDone ? 100 : Math.round((currentStage / 7) * 100);

  return (
    <div className="space-y-6 animate-slide-up">
      {/* Overall progress bar */}
      <div className="space-y-2">
        <div className="flex justify-between items-center">
          <span className="text-sm font-medium text-slate-300">
            {isDone ? 'Complete!' : hasError ? 'Error' : 'Running pipeline...'}
          </span>
          <span className="text-sm text-brand-400 font-mono">{progress}%</span>
        </div>
        <div className="progress-track">
          <div
            className={`progress-fill ${hasError ? 'bg-red-500' : ''}`}
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      {/* Stage dots */}
      <div className="flex items-center gap-2 overflow-x-auto pb-2">
        {STAGE_LABELS.map((label, idx) => {
          const stageNum = idx + 1;
          const done = isDone || stageNum < currentStage;
          const active = stageNum === currentStage && isRunning;
          const status = done ? 'done' : active ? 'active' : 'pending';
          return (
            <React.Fragment key={stageNum}>
              <div className="flex flex-col items-center gap-1.5 flex-shrink-0">
                <div className={`stage-dot ${status}`}>
                  {done
                    ? <CheckCircle className="w-4 h-4" />
                    : active
                      ? <Loader2 className="w-4 h-4 animate-spin" />
                      : <span>{stageNum}</span>}
                </div>
                <span className={`text-xs text-center max-w-16 leading-tight
                  ${done ? 'text-emerald-400' : active ? 'text-brand-400' : 'text-slate-600'}`}>
                  {label}
                </span>
              </div>
              {idx < STAGE_LABELS.length - 1 && (
                <div className={`h-px flex-1 min-w-4 transition-colors duration-500
                  ${stageNum < currentStage ? 'bg-emerald-500/50' : 'bg-white/10'}`} />
              )}
            </React.Fragment>
          );
        })}
      </div>

      {/* Latest message */}
      {latestMessage && !hasError && (
        <div className="px-4 py-3 rounded-xl bg-brand-500/10 border border-brand-500/20">
          <p className="text-sm text-brand-300 flex items-center gap-2">
            {isRunning && <Loader2 className="w-3 h-3 animate-spin flex-shrink-0" />}
            {latestMessage}
          </p>
        </div>
      )}

      {/* Error */}
      {hasError && errorMsg && (
        <div className="px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/20">
          <p className="text-sm text-red-400 flex items-center gap-2">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            {errorMsg}
          </p>
        </div>
      )}

      {/* Event log (scrollable) */}
      <div className="space-y-1 max-h-40 overflow-y-auto">
        {events
          .filter(e => e.message && !e.keepalive)
          .map((e, i) => (
            <div key={i} className="flex items-start gap-2 text-xs text-slate-500 animate-fade-in">
              <Clock className="w-3 h-3 flex-shrink-0 mt-0.5 text-slate-600" />
              <span>{e.message}</span>
            </div>
          ))}
      </div>
    </div>
  );
}
