"use client";

import {
  Play,
  Pause,
  RotateCcw,
  SkipBack,
  SkipForward,
  Gauge,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useShowcase } from "./showcase-context";
import { useTranslations, useLocale } from "@/lib/i18n";
import Link from "next/link";
import { LEARNING_PATH } from "@/lib/constants";

interface ShowcasePlayerBarProps {
  version: string;
}

const SPEED_OPTIONS = [0.5, 1, 1.5, 2];

export function ShowcasePlayerBar({ version }: ShowcasePlayerBarProps) {
  const {
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
    setSpeed,
    isFirstStep,
    isLastStep,
  } = useShowcase();

  const t = useTranslations("showcase");
  const locale = useLocale();

  const pathIndex = LEARNING_PATH.indexOf(version as (typeof LEARNING_PATH)[number]);
  const prevVersion = pathIndex > 0 ? LEARNING_PATH[pathIndex - 1] : null;
  const nextVersion =
    pathIndex < LEARNING_PATH.length - 1 ? LEARNING_PATH[pathIndex + 1] : null;

  const togglePlay = () => {
    if (isPlaying) pause();
    else play();
  };

  return (
    <div className="flex h-16 items-center gap-3 border-t border-zinc-700 bg-zinc-900 px-4">
      {/* Task navigation */}
      <div className="flex items-center gap-1">
        {prevVersion ? (
          <Link
            href={`/${locale}/showcase/${prevVersion}`}
            className="flex items-center gap-1 rounded-md px-2 py-1.5 text-xs text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-white"
          >
            <ChevronLeft size={14} />
            <span className="hidden sm:inline">{prevVersion}</span>
          </Link>
        ) : (
          <div className="w-12" />
        )}
        <span className="font-mono text-xs text-zinc-500">
          {version}
        </span>
        {nextVersion ? (
          <Link
            href={`/${locale}/showcase/${nextVersion}`}
            className="flex items-center gap-1 rounded-md px-2 py-1.5 text-xs text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-white"
          >
            <span className="hidden sm:inline">{nextVersion}</span>
            <ChevronRight size={14} />
          </Link>
        ) : (
          <div className="w-12" />
        )}
      </div>

      <div className="h-6 w-px bg-zinc-700" />

      {/* Playback controls */}
      <div className="flex items-center gap-1">
        <button
          onClick={reset}
          title="Reset"
          className="rounded-md p-1.5 text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-white"
        >
          <RotateCcw size={15} />
        </button>
        <button
          onClick={() => prev()}
          disabled={isFirstStep}
          title="Previous step"
          className="rounded-md p-1.5 text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-white disabled:opacity-30"
        >
          <SkipBack size={15} />
        </button>
        <button
          onClick={togglePlay}
          title={isPlaying ? "Pause" : "Play"}
          className={cn(
            "rounded-md p-2 transition-colors",
            isPlaying
              ? "bg-blue-600 text-white hover:bg-blue-500"
              : "bg-zinc-700 text-white hover:bg-zinc-600"
          )}
        >
          {isPlaying ? <Pause size={16} /> : <Play size={16} />}
        </button>
        <button
          onClick={() => next()}
          disabled={isLastStep}
          title="Next step"
          className="rounded-md p-1.5 text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-white disabled:opacity-30"
        >
          <SkipForward size={15} />
        </button>
      </div>

      <div className="h-6 w-px bg-zinc-700" />

      {/* Progress bar */}
      <div className="flex flex-1 items-center gap-2">
        <span className="shrink-0 font-mono text-xs text-zinc-500">
          {currentStep + 1}/{totalSteps}
        </span>
        <div className="relative h-2 flex-1 cursor-pointer rounded-full bg-zinc-700">
          {/* Filled portion */}
          <div
            className="absolute left-0 top-0 h-2 rounded-full bg-blue-500 transition-all duration-300"
            style={{
              width: `${totalSteps > 1 ? (currentStep / (totalSteps - 1)) * 100 : 0}%`,
            }}
          />
          {/* Step dots */}
          <div className="absolute inset-0 flex items-center">
            {Array.from({ length: totalSteps }, (_, i) => (
              <button
                key={i}
                onClick={() => goToStep(i)}
                title={`Step ${i + 1}`}
                className="group relative flex-1 py-1"
              >
                <div
                  className={cn(
                    "mx-auto h-2 w-2 rounded-full transition-all",
                    i <= currentStep
                      ? "scale-110 bg-blue-400 group-hover:scale-125 group-hover:bg-blue-300"
                      : "bg-zinc-600 group-hover:scale-125 group-hover:bg-zinc-400"
                  )}
                />
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="h-6 w-px bg-zinc-700" />

      {/* Speed control */}
      <div className="flex items-center gap-1.5">
        <Gauge size={14} className="shrink-0 text-zinc-500" />
        <div className="flex items-center rounded-md border border-zinc-700 bg-zinc-800">
          {SPEED_OPTIONS.map((s) => (
            <button
              key={s}
              onClick={() => setSpeed(s)}
              className={cn(
                "px-2 py-1 text-xs font-medium transition-colors",
                speed === s
                  ? "bg-zinc-600 text-white"
                  : "text-zinc-400 hover:text-white"
              )}
            >
              {s}x
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
