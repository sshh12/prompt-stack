import React, { useState, useRef, useEffect } from 'react';

const Splitter = ({
  children,
  className = '',
  minLeftWidth = 300,
  minRightWidth = 50,
  defaultLeftWidth = '70%'
}) => {
  const [isDragging, setIsDragging] = useState(false);
  const [leftWidth, setLeftWidth] = useState(defaultLeftWidth);
  const containerRef = useRef(null);
  const leftPaneRef = useRef(null);
  const rightPaneRef = useRef(null);

  const handleMouseDown = (e) => {
    e.preventDefault();
    setIsDragging(true);
  };

  useEffect(() => {
    const handleMouseMove = (e) => {
      if (!isDragging || !containerRef.current) return;

      const container = containerRef.current;
      const containerRect = container.getBoundingClientRect();
      const newLeftWidth = e.clientX - containerRect.left;

      // Calculate the right width based on the new left width
      const rightWidth = containerRect.width - newLeftWidth;

      // Only update if both panes meet minimum width requirements
      if (newLeftWidth >= minLeftWidth && rightWidth >= minRightWidth) {
        setLeftWidth(`${(newLeftWidth / containerRect.width) * 100}%`);
      }
    };

    const handleMouseUp = () => {
      setIsDragging(false);
    };

    if (isDragging) {
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
    }

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging, minLeftWidth, minRightWidth]);

  const [leftChild, rightChild] = React.Children.toArray(children);

  return (
    <div ref={containerRef} className={`flex h-full w-full ${className}`}>
      <div
        ref={leftPaneRef}
        className="flex-shrink-0"
        style={{ width: leftWidth }}
      >
        {leftChild}
      </div>

      <div
        className={`w-1 bg-border hover:bg-primary/10 cursor-col-resize flex-shrink-0 relative ${
          isDragging ? 'bg-primary/10' : ''
        }`}
        onMouseDown={handleMouseDown}
      >
        <div className="absolute inset-y-0 -left-2 right-2 cursor-col-resize" />
      </div>

      <div ref={rightPaneRef} className="flex-1 min-w-0">
        {rightChild}
      </div>
    </div>
  );
};

export default Splitter;