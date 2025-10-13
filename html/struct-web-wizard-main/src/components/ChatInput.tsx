import { useState, useRef } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Send, Paperclip, BookOpen, Image, CloudCog } from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import FilePreview from "./FilePreview";

interface ChatInputProps {
  onSend: (message: string) => void;
  isLoading: boolean;
}

const ChatInput = ({ onSend, isLoading }: ChatInputProps) => {
  const [input, setInput] = useState("");
  const [model, setModel] = useState("google/gemini-2.5-flash");
  const [isAttachmentOpen, setIsAttachmentOpen] = useState(false);
  const [attachedFiles, setAttachedFiles] = useState<File[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleSend = () => {
    if (input.trim() && !isLoading) {
      onSend(input.trim());
      setInput("");
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files) {
      const newFiles = Array.from(files);
      setAttachedFiles((prev) => [...prev, ...newFiles]);
    }
    // Reset input value to allow selecting the same file again
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const handleRemoveFile = (index: number) => {
    setAttachedFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const openFilePicker = () => {
    setIsAttachmentOpen(false);
    fileInputRef.current?.click();
  };

  const attachmentOptions = [
    {
      icon: BookOpen,
      label: "지식베이스 라이브러리에서 첨부",
      onClick: () => {
        console.log("지식베이스 라이브러리");
        setIsAttachmentOpen(false);
      },
    },
    {
      icon: Image,
      label: "사진 및 파일 첨부",
      onClick: openFilePicker,
    },
    {
      icon: CloudCog,
      label: "구글 드라이브에서 첨부",
      onClick: () => {
        console.log("구글 드라이브");
        setIsAttachmentOpen(false);
      },
    },
  ];

  return (
    <div className="border-t bg-background p-4">
      <div className="max-w-4xl mx-auto space-y-3">
        {/* File Previews */}
        {attachedFiles.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {attachedFiles.map((file, index) => (
              <FilePreview
                key={index}
                file={file}
                onRemove={() => handleRemoveFile(index)}
              />
            ))}
          </div>
        )}

        <div className="flex items-center gap-2">
          {/* Hidden file input */}
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*,.pdf,.doc,.docx,.txt"
            multiple
            className="hidden"
            onChange={handleFileSelect}
          />
          <Popover open={isAttachmentOpen} onOpenChange={setIsAttachmentOpen}>
            <PopoverTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="flex-shrink-0"
              >
                <Paperclip className="h-5 w-5" />
              </Button>
            </PopoverTrigger>
            <PopoverContent 
              className="w-80 p-2" 
              align="start"
              side="top"
            >
              <div className="space-y-1">
                {attachmentOptions.map((option, index) => (
                  <button
                    key={index}
                    onClick={option.onClick}
                    className="w-full flex items-center gap-3 px-3 py-3 rounded-lg hover:bg-muted transition-colors text-left"
                  >
                    <option.icon className="h-5 w-5 flex-shrink-0" />
                    <span className="text-sm">{option.label}</span>
                  </button>
                ))}
              </div>
            </PopoverContent>
          </Popover>
          
          <Select value={model} onValueChange={setModel}>
            <SelectTrigger className="w-[200px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="google/gemini-2.5-flash">
                gemini-2.5-flash
              </SelectItem>
              <SelectItem value="google/gemini-2.5-pro">
                gemini-2.5-pro
              </SelectItem>
              <SelectItem value="google/gemini-2.5-flash-lite">
                gemini-2.5-flash-lite
              </SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="flex items-end gap-2">
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder="메세지를 입력하세요."
            className="min-h-[60px] max-h-[120px] resize-none"
            disabled={isLoading}
          />
          
          <Button
            onClick={handleSend}
            disabled={!input.trim() || isLoading}
            size="icon"
            className="h-[60px] w-[60px] flex-shrink-0 bg-accent hover:bg-accent/90"
          >
            <Send className="h-5 w-5" />
          </Button>
        </div>
      </div>
    </div>
  );
};

export default ChatInput;
