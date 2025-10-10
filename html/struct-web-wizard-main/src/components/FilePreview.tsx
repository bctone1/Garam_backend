import { X, FileText, Image as ImageIcon } from "lucide-react";
import { Button } from "@/components/ui/button";

interface FilePreviewProps {
  file: File;
  onRemove: () => void;
}

const FilePreview = ({ file, onRemove }: FilePreviewProps) => {
  const isImage = file.type.startsWith("image/");
  const isPDF = file.type === "application/pdf";
  const fileSize = (file.size / (1024 * 1024)).toFixed(2);

  return (
    <div className="relative flex items-center gap-3 bg-accent/10 rounded-2xl p-3 border border-border">
      <div className="relative">
        {isImage ? (
          <div className="w-16 h-16 rounded-lg overflow-hidden bg-muted flex items-center justify-center">
            <img
              src={URL.createObjectURL(file)}
              alt={file.name}
              className="w-full h-full object-cover"
            />
          </div>
        ) : (
          <div className="w-16 h-16 rounded-lg bg-primary/10 flex items-center justify-center">
            <FileText className="h-8 w-8 text-primary" />
          </div>
        )}
        <Button
          variant="ghost"
          size="icon"
          className="absolute -top-2 -right-2 h-6 w-6 rounded-full bg-background border shadow-sm hover:bg-destructive hover:text-destructive-foreground"
          onClick={onRemove}
        >
          <X className="h-4 w-4" />
        </Button>
      </div>

      <div className="flex-1 min-w-0">
        <p className="font-medium text-sm truncate">{file.name}</p>
        <p className="text-xs text-muted-foreground">
          {isPDF ? "PDF" : isImage ? "이미지" : "파일"} | {fileSize}MB
        </p>
      </div>
    </div>
  );
};

export default FilePreview;
