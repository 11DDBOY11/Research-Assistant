'use client';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Sparkles, Play, Download, RefreshCw, FileText,
  BookOpen, CheckCircle, AlertCircle, Zap
} from 'lucide-react';

import UploadZone from '../components/UploadZone';
import PipelineProgress from '../components/PipelineProgress';
import ClarificationForm from '../components/ClarificationForm';
import PaperPreview from '../components/PaperPreview';
import TransparencyReportComponent from '../components/TransparencyReport';

import {
  uploadLiterature, uploadProject, getUploadStatus,
  startPipeline, subscribeToPipeline,
  getClarifications, getDownloadUrl, getPaperPreview,
} from '../lib/api';
import type {
  AppStage, ClarificationRequest, PaperPreviewData, PipelineEvent, UploadedFile,
} from '../lib/types';

export default function Home() {
  // Upload state
  const [litCount, setLitCount] = useState(0);
  const [projCount, setProjCount] = useState(0);
  const [litFiles, setLitFiles] = useState<UploadedFile[]>([]);

  // Pipeline state
  const [appStage, setAppStage] = useState<AppStage>('upload');
  const [pipelineEvents, setPipelineEvents] = useState<PipelineEvent[]>([]);
  const [pipelineError, setPipelineError] = useState<string | null>(null);

  // Clarifications
  const [clarifications, setClarifications] = useState<ClarificationRequest[]>([]);

  // Output
  const [preview, setPreview] = useState<PaperPreviewData | null>(null);

  // SSE cleanup ref
  const unsubRef = useRef<(() => void) | null>(null);

  // Load upload status on mount
  useEffect(() => {
    getUploadStatus()
      .then(s => {
        setLitCount(s.literature_count);
        setProjCount(s.project_count);
        setLitFiles(s.literature_files);
      })
      .catch(() => {});
  }, []);

  const refreshUploadStatus = useCallback(async () => {
    const s = await getUploadStatus();
    setLitCount(s.literature_count);
    setProjCount(s.project_count);
    setLitFiles(s.literature_files);
  }, []);

  const handleLiteratureUpload = async (files: File[]) => {
    await uploadLiterature(files);
    await refreshUploadStatus();
  };

  const handleProjectUpload = async (files: File[]) => {
    await uploadProject(files[0]);
    await refreshUploadStatus();
  };

  const handleRunPipeline = async () => {
    setAppStage('running');
    setPipelineEvents([]);
    setPipelineError(null);

    try {
      const { run_id } = await startPipeline();
      unsubRef.current = subscribeToPipeline(
        run_id,
        (event) => {
          setPipelineEvents(prev => [...prev, event]);

          // After pipeline done: load clarifications + preview
          if (event.done) {
            setAppStage('complete');
            // Load clarifications (may still have unresolved ones)
            getClarifications().then(r => setClarifications(r.clarifications)).catch(() => {});
            // Load paper preview
            getPaperPreview().then(setPreview).catch(() => {});
          }
          if (event.clarifications_needed && event.clarifications_needed > 0) {
            getClarifications().then(r => setClarifications(r.clarifications)).catch(() => {});
          }
        },
        (err) => {
          setPipelineError(err);
          setAppStage('error');
        }
      );
    } catch (err: any) {
      setPipelineError(err?.message || 'Failed to start pipeline');
      setAppStage('error');
    }
  };

  const handleReset = async () => {
    if (unsubRef.current) { unsubRef.current(); unsubRef.current = null; }
    try {
      await fetch('/api/upload/reset', { method: 'DELETE' });
    } catch {}
    setAppStage('upload');
    setPipelineEvents([]);
    setPipelineError(null);
    setClarifications([]);
    setPreview(null);
    setLitCount(0);
    setProjCount(0);
    setLitFiles([]);
  };

  const isRunning = appStage === 'running';
  const isComplete = appStage === 'complete';
  const hasError = appStage === 'error';
  const canRun = litCount > 0 && projCount > 0 && !isRunning;
  const unresolvedClarifications = clarifications.filter(c => !c.resolved);

  return (
    <main className="min-h-screen">
      {/* ── Header ── */}
      <header className="border-b border-white/10 px-6 py-4 flex items-center gap-3">
        <div className="w-9 h-9 rounded-xl bg-brand-500/20 border border-brand-500/30 flex items-center justify-center">
          <Sparkles className="w-5 h-5 text-brand-400" />
        </div>
        <div>
          <h1 className="text-base font-bold text-white leading-tight">Research Paper Assistant</h1>
          <p className="text-xs text-slate-500">Every sentence traceable to its source</p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {(litCount > 0 || projCount > 0) && (
            <button onClick={handleReset} className="btn-danger" id="reset-session">
              <RefreshCw className="w-3.5 h-3.5" />
              Start over
            </button>
          )}
          {isComplete && (
            <a
              href={getDownloadUrl()}
              download="generated_paper.docx"
              className="btn-primary text-sm py-2"
              id="download-docx"
            >
              <Download className="w-4 h-4" />
              Download DOCX
            </a>
          )}
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-4 py-6">
        {/* ── Final view: paper preview + transparency report ── */}
        {isComplete && preview ? (
          <div className="animate-slide-up space-y-4">
            <div className="flex items-center gap-3 mb-2">
              <CheckCircle className="w-5 h-5 text-emerald-400" />
              <p className="text-emerald-400 font-medium">
                Your paper is ready — {preview.sentence_count} verified sentences across {preview.section_count} sections.
              </p>
            </div>

            {/* Clarifications inline (if any still unresolved) */}
            {unresolvedClarifications.length > 0 && (
              <div className="card p-5 mb-4">
                <ClarificationForm
                  clarifications={unresolvedClarifications}
                  onResolved={() => getClarifications().then(r => setClarifications(r.clarifications))}
                />
              </div>
            )}

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 h-[calc(100vh-220px)]">
              {/* Paper preview */}
              <div className="card p-6 overflow-hidden">
                <PaperPreview data={preview} />
              </div>

              {/* Transparency report */}
              <div className="card p-6 overflow-hidden">
                <TransparencyReportComponent report={preview.transparency} />
              </div>
            </div>
          </div>
        ) : (
          /* ── Main upload + pipeline UI ── */
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {/* Left: Upload zones */}
            <div className="lg:col-span-1 space-y-4">
              <div className="card p-5 space-y-5">
                <div className="flex items-center gap-2">
                  <Zap className="w-4 h-4 text-brand-400" />
                  <h2 className="text-sm font-semibold text-slate-200">Upload Files</h2>
                </div>

                <UploadZone
                  role="literature"
                  onUpload={handleLiteratureUpload}
                  maxFiles={15}
                  currentCount={litCount}
                  maxCount={15}
                  disabled={isRunning}
                />

                <div className="h-px bg-white/10" />

                <UploadZone
                  role="project"
                  onUpload={handleProjectUpload}
                  disabled={isRunning}
                />
              </div>

              {/* Uploaded literature file list */}
              {litFiles.length > 0 && (
                <div className="card p-4 space-y-2 animate-fade-in">
                  <p className="text-xs font-medium text-slate-400 uppercase tracking-wide">
                    Literature files
                  </p>
                  <div className="space-y-1.5 max-h-40 overflow-y-auto">
                    {litFiles.map(f => (
                      <div key={f.id} className="flex items-center gap-2 text-xs text-slate-400">
                        <FileText className="w-3 h-3 text-slate-600 flex-shrink-0" />
                        <span className="truncate flex-1">{f.filename}</span>
                        <span className={`flex-shrink-0 ${
                          f.status === 'extracted' ? 'text-emerald-500' : 'text-slate-600'
                        }`}>
                          {f.status === 'extracted' ? '✓' : '·'}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Run button */}
              <button
                onClick={handleRunPipeline}
                disabled={!canRun}
                className="btn-primary w-full justify-center"
                id="run-pipeline"
              >
                {isRunning
                  ? <><div className="w-4 h-4 border-2 border-white/50 border-t-transparent rounded-full animate-spin" /> Running...</>
                  : <><Play className="w-4 h-4" /> Run Pipeline</>}
              </button>

              {!canRun && !isRunning && (
                <p className="text-xs text-center text-slate-600">
                  {litCount === 0
                    ? 'Upload at least 1 literature file'
                    : 'Upload your project file to continue'}
                </p>
              )}
            </div>

            {/* Right: Progress + clarifications */}
            <div className="lg:col-span-2 space-y-4">
              {(isRunning || hasError || pipelineEvents.length > 0) && (
                <div className="card p-6">
                  <PipelineProgress
                    events={pipelineEvents}
                    isRunning={isRunning}
                    hasError={hasError}
                    errorMsg={pipelineError ?? undefined}
                  />
                </div>
              )}

              {unresolvedClarifications.length > 0 && (
                <div className="card p-5">
                  <ClarificationForm
                    clarifications={unresolvedClarifications}
                    onResolved={() => getClarifications().then(r => setClarifications(r.clarifications))}
                  />
                </div>
              )}

              {/* Empty state */}
              {!isRunning && !hasError && pipelineEvents.length === 0 && (
                <div className="card p-12 flex flex-col items-center gap-4 text-center animate-fade-in">
                  <div className="w-16 h-16 rounded-2xl bg-brand-500/10 border border-brand-500/20 flex items-center justify-center">
                    <BookOpen className="w-8 h-8 text-brand-500/50" />
                  </div>
                  <div>
                    <p className="text-slate-400 font-medium">Ready to analyze</p>
                    <p className="text-sm text-slate-600 mt-1 max-w-sm">
                      Upload your literature PDFs and project file on the left, then click
                      "Run Pipeline" to generate your evidence-backed paper.
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2 justify-center mt-2">
                    {['Upload files', 'Extract claims', 'Compare & match', 'Generate paper', 'Verify citations', 'Download DOCX'].map((step, i) => (
                      <span key={i} className="text-xs px-3 py-1 rounded-full bg-white/5 border border-white/10 text-slate-500">
                        {i + 1}. {step}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
