'use client';
import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { BookOpen } from 'lucide-react';
import type { PaperPreviewData } from '../lib/types';

interface Props {
  data: PaperPreviewData;
}

export default function PaperPreview({ data }: Props) {
  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center gap-2 mb-4 flex-shrink-0">
        <BookOpen className="w-5 h-5 text-brand-400" />
        <h2 className="text-lg font-semibold text-white">Generated Paper</h2>
        <span className="ml-auto badge badge-verified">
          {data.sentence_count} sentences · {data.section_count} sections
        </span>
      </div>

      {/* Scrollable markdown preview */}
      <div className="flex-1 overflow-y-auto pr-2">
        <div className="prose-dark">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {data.markdown}
          </ReactMarkdown>
        </div>
      </div>
    </div>
  );
}
