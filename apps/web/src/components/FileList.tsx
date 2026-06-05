import { Download, FileText } from "lucide-react";

import type { GeneratedFile } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface Props {
  files: GeneratedFile[];
}

const KIND_LABEL: Record<GeneratedFile["kind"], string> = {
  docx: "DOCX",
  pdf: "PDF",
  latex_pdf: "LaTeX PDF",
  other: "File",
};

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

export default function FileList({ files }: Props) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Files ({files.length})</CardTitle>
      </CardHeader>
      <CardContent>
        {files.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No files yet — generate the CV or cover letter to produce them.
          </p>
        ) : (
          <ul className="divide-y">
            {files.map((f) => (
              <li
                key={f.filename}
                className="flex items-center justify-between gap-3 py-2"
              >
                <div className="flex min-w-0 items-center gap-2">
                  <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <span className="truncate text-sm">{f.filename}</span>
                </div>
                <div className="flex shrink-0 items-center gap-3 text-xs text-muted-foreground">
                  <span>{KIND_LABEL[f.kind]}</span>
                  <span className="tabular-nums">{formatSize(f.size_bytes)}</span>
                  <a
                    href={f.download_url}
                    download={f.filename}
                    className="inline-flex items-center gap-1 text-foreground hover:underline"
                  >
                    <Download className="h-3.5 w-3.5" />
                    Download
                  </a>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
