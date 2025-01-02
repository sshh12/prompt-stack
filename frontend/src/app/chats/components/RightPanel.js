'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { PreviewTab } from './PreviewTab';
import { FilesTab } from './FilesTab';
import { ProjectTab } from './ProjectTab';

export function RightPanel({
  projectPreviewUrl,
  projectPreviewHash,
  projectFileTree,
  project,
  projectPreviewPath,
  setProjectPreviewPath,
  onSendMessage,
  status,
}) {
  const [selectedTab, setSelectedTab] = useState('preview');

  return (
    <div className="flex flex-col w-full h-full">
      <div className="border-b bg-background">
        <div className="flex items-center space-x-4 px-4 py-2">
          <Button
            variant={selectedTab === 'preview' ? 'default' : 'ghost'}
            size="sm"
            onClick={() => setSelectedTab('preview')}
          >
            Preview
          </Button>
          <Button
            variant={selectedTab === 'editor' ? 'default' : 'ghost'}
            size="sm"
            onClick={() => setSelectedTab('editor')}
          >
            Files
          </Button>
          <Button
            variant={selectedTab === 'info' ? 'default' : 'ghost'}
            size="sm"
            onClick={() => setSelectedTab('info')}
          >
            Project
          </Button>
        </div>
      </div>
      <div className="flex-1 overflow-hidden">
        {selectedTab === 'preview' ? (
          <PreviewTab
            projectPreviewUrl={projectPreviewUrl}
            projectPreviewHash={projectPreviewHash}
            projectPreviewPath={projectPreviewPath}
            setProjectPreviewPath={setProjectPreviewPath}
            status={status}
          />
        ) : selectedTab === 'editor' ? (
          <FilesTab projectFileTree={projectFileTree} project={project} />
        ) : (
          <ProjectTab project={project} onSendMessage={onSendMessage} />
        )}
      </div>
    </div>
  );
}