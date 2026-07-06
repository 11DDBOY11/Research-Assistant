'use client';
import React, { useCallback, useState } from 'react';
import { useDropzone, FileRejection } from 'react-dropzone';
import { Upload, CheckCircle, AlertCircle, BookOpen, FolderOpen } from 'lucide-react';

interface Props {
  role: 'literature' | 'project';
  onUpload: (files: File[]) => Promise<void>;
  maxFiles?: number;
  currentCount?: number;
  maxCount?: number;
  disabled?: boolean;
}

const ACCEPT = {
  'application/pdf': ['.pdf'],
  'text/plain': ['.txt'],
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
};

export default function UploadZone({ role, onUpload, maxFiles = 15, currentCount = 0, maxCount = 15, disabled }: Props) {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const isLiterature = role === 'literature';

  const MAX_SIZE_BYTES = 20 * 1024 * 1024; // 20MB, matches UI label below

  const onDrop = useCallback(async (accepted: File[], rejected: FileRejection[]) => {
    setError(null);
    setSuccessMsg(null);

    if (rejected.length > 0) {
      const reasons = rejected.map((r) => r.errors[0]?.code);
      const msg = reasons.includes('file-too-large')
        ? 'One or more files exceed the 20MB limit.'
        : reasons.includes('file-invalid-type')
          ? 'Only PDF, TXT, or DOCX files are allowed.'
          : 'Some files were rejected.';
      setError(msg);
    }

    if (isLiterature && currentCount + accepted.length > maxCount) {
      const allowed = Math.max(maxCount - currentCount, 0);
      setError(
        allowed === 0
          ? `Limit reached: ${maxCount} files max.`
          : `Only ${allowed} more file${allowed > 1 ? 's' : ''} allowed (${maxCount} max).`
      );
      accepted = accepted.slice(0, allowed);
    }

    if (!accepted.length) return;

    setUploading(true);
    try {
      await onUpload(accepted);
      setSuccessMsg(
        isLiterature
          ? `${accepted.length} file${accepted.length > 1 ? 's' : ''} uploaded`
          : `${accepted[0].name} uploaded`
      );
    } catch (err: any) {
      setError(err?.message || 'Upload failed');
    } finally {
      setUploading(false);
    }
  }, [onUpload, isLiterature, currentCount, maxCount]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: ACCEPT,
    multiple: isLiterature,
    maxFiles: isLiterature ? maxFiles : 1,
    maxSize: MAX_SIZE_BYTES,
    disabled: disabled || uploading,
  });

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center gap-2">
        {isLiterature
          ? <BookOpen className="w-4 h-4 text-brand-400" />
          : <FolderOpen className="w-4 h-4 text-violet-400" />}
        <span className="text-sm font-medium text-slate-300">
          {isLiterature ? 'Literature Papers' : 'Your Project File'}
        </span>
        {isLiterature && (
          <span className="ml-auto text-xs text-slate-500">
            {currentCount}/{maxCount} files
          </span>
        )}
      </div>

      {/* Drop zone */}
      <div
        {...getRootProps()}
        className={`drop-zone ${isDragActive ? 'active' : ''} ${disabled || uploading ? 'opacity-50 cursor-not-allowed' : ''}`}
        id={`dropzone-${role}`}
      >
        <input {...getInputProps()} />
        <div className="flex flex-col items-center gap-3 text-center pointer-events-none">
          <div className={`w-12 h-12 rounded-2xl flex items-center justify-center transition-all duration-300
            ${isDragActive
              ? 'bg-brand-500/20 scale-110'
              : 'bg-white/5'}`}>
            {uploading
              ? <div className="w-5 h-5 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
              : <Upload className={`w-5 h-5 ${isDragActive ? 'text-brand-400' : 'text-slate-500'}`} />
            }
          </div>
          <div>
            <p className="text-sm font-medium text-slate-300">
              {uploading
                ? 'Uploading...'
                : isDragActive
                  ? 'Drop to upload'
                  : isLiterature
                    ? 'Drop PDFs here or click to browse'
                    : 'Drop your project file here'}
            </p>
            <p className="text-xs text-slate-500 mt-1">
              {isLiterature
                ? `Up to ${maxCount} files · PDF, TXT, or DOCX · 20MB max each`
                : 'PDF, TXT, or DOCX · 20MB max'}
            </p>
          </div>
        </div>
      </div>

      {/* Feedback */}
      {error && (
        <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/20 animate-fade-in">
          <AlertCircle className="w-4 h-4 text-red-400 flex-shrink-0 mt-0.5" />
          <p className="text-xs text-red-400">{error}</p>
        </div>
      )}
      {successMsg && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20 animate-fade-in">
          <CheckCircle className="w-4 h-4 text-emerald-400" />
          <p className="text-xs text-emerald-400">{successMsg}</p>
        </div>
      )}
    </div>
  );
}