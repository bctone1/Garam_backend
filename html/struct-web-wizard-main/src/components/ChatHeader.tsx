import { Menu, Search, Phone, MoreVertical } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";

const ChatHeader = () => {
  const participants = [
    { id: 1, name: "민정" },
    { id: 2, name: "동우" },
    { id: 3, name: "현아" },
  ];

  return (
    <header className="bg-background border-b sticky top-0 z-10">
      <div className="max-w-4xl mx-auto flex items-center justify-between px-4 py-3">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon">
            <Menu className="h-5 w-5" />
          </Button>
          
          <div className="flex items-center gap-2">
            <h1 className="text-lg font-semibold">대화장 제목</h1>
            <span className="text-sm text-muted-foreground">5</span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <div className="flex -space-x-2">
            {participants.map((p) => (
              <Avatar key={p.id} className="h-8 w-8 border-2 border-background">
                <AvatarFallback className="text-xs">
                  {p.name[0]}
                </AvatarFallback>
              </Avatar>
            ))}
          </div>
          
          <Button variant="ghost" size="icon">
            <Search className="h-5 w-5" />
          </Button>
          
          <Button variant="ghost" size="icon">
            <Phone className="h-5 w-5" />
          </Button>
          
          <Button variant="ghost" size="icon">
            <MoreVertical className="h-5 w-5" />
          </Button>
        </div>
      </div>
    </header>
  );
};

export default ChatHeader;
