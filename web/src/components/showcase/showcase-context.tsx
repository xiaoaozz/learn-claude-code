"use client";

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  useRef,
  ReactNode,
} from "react";

interface ShowcaseContextValue {
  // Current global step across all panels
  currentStep: number;
  totalSteps: number;
  isPlaying: boolean;
  speed: number;
  // Controls
  play: () => void;
  pause: () => void;
  reset: () => void;
  next: () => void;
  prev: () => void;
  goToStep: (step: number) => void;
  setTotalSteps: (n: number) => void;
  setSpeed: (s: number) => void;
  isFirstStep: boolean;
  isLastStep: boolean;
  // Active panel highlight
  activePanel: "learning" | "visualization" | "simulator" | null;
  setActivePanel: (p: "learning" | "visualization" | "simulator" | null) => void;
}

const ShowcaseContext = createContext<ShowcaseContextValue | null>(null);

export function useShowcase() {
  const ctx = useContext(ShowcaseContext);
  if (!ctx) throw new Error("useShowcase must be used within ShowcaseProvider");
  return ctx;
}

interface ShowcaseProviderProps {
  children: ReactNode;
  initialTotalSteps?: number;
}

export function ShowcaseProvider({
  children,
  initialTotalSteps = 1,
}: ShowcaseProviderProps) {
  const [currentStep, setCurrentStep] = useState(0);
  const [totalSteps, setTotalSteps] = useState(initialTotalSteps);
  const [isPlaying, setIsPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [activePanel, setActivePanel] = useState<
    "learning" | "visualization" | "simulator" | null
  >(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const clearPlayInterval = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  const play = useCallback(() => {
    setIsPlaying(true);
  }, []);

  const pause = useCallback(() => {
    setIsPlaying(false);
    clearPlayInterval();
  }, [clearPlayInterval]);

  const reset = useCallback(() => {
    setIsPlaying(false);
    clearPlayInterval();
    setCurrentStep(0);
  }, [clearPlayInterval]);

  const next = useCallback(() => {
    setCurrentStep((prev) => Math.min(prev + 1, totalSteps - 1));
  }, [totalSteps]);

  const prev = useCallback(() => {
    setCurrentStep((prev) => Math.max(prev - 1, 0));
  }, []);

  const goToStep = useCallback(
    (step: number) => {
      setCurrentStep(Math.max(0, Math.min(step, totalSteps - 1)));
    },
    [totalSteps]
  );

  // Auto-play effect
  useEffect(() => {
    if (isPlaying) {
      const interval = Math.round(2500 / speed);
      intervalRef.current = setInterval(() => {
        setCurrentStep((prev) => {
          if (prev >= totalSteps - 1) {
            setIsPlaying(false);
            return prev;
          }
          return prev + 1;
        });
      }, interval);
    }
    return () => clearPlayInterval();
  }, [isPlaying, totalSteps, speed, clearPlayInterval]);

  // Stop playing when reaching end
  useEffect(() => {
    if (currentStep >= totalSteps - 1 && isPlaying) {
      setIsPlaying(false);
    }
  }, [currentStep, totalSteps, isPlaying]);

  return (
    <ShowcaseContext.Provider
      value={{
        currentStep,
        totalSteps,
        isPlaying,
        speed,
        play,
        pause,
        reset,
        next,
        prev,
        goToStep,
        setTotalSteps,
        setSpeed,
        isFirstStep: currentStep === 0,
        isLastStep: currentStep >= totalSteps - 1,
        activePanel,
        setActivePanel,
      }}
    >
      {children}
    </ShowcaseContext.Provider>
  );
}
