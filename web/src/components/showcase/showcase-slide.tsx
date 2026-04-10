"use client";

import { lazy, Suspense, useEffect, useState, useRef, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useTranslations, useLocale } from "@/lib/i18n";
import { VERSION_META, LAYERS, LEARNING_PATH } from "@/lib/constants";
import { LayerBadge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import {
  Lightbulb,
  Plus,
  BookOpen,
  BarChart3,
  Terminal,
  ChevronRight,
  ChevronLeft,
  Play,
  LayoutGrid,
  Maximize2,
  Minimize2,
} from "lucide-react";
import docsData from "@/data/generated/docs.json";
import type { Scenario } from "@/types/agent-data";
import { useSimulator } from "@/hooks/useSimulator";
import { AnimatePresence as AnimPresence } from "framer-motion";
import { SimulatorMessage } from "@/components/simulator/simulator-message";
import { SimulatorControls } from "@/components/simulator/simulator-controls";
import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkGfm from "remark-gfm";
import remarkRehype from "remark-rehype";
import rehypeRaw from "rehype-raw";
import rehypeHighlight from "rehype-highlight";
import rehypeStringify from "rehype-stringify";
import Link from "next/link";

// ─── Visualization lazy map ───────────────────────────────────────────────────
const vizComponents: Record<
  string,
  React.LazyExoticComponent<React.ComponentType<{ title?: string }>>
> = {
  s01: lazy(() => import("@/components/visualizations/s01-agent-loop")),
  s02: lazy(() => import("@/components/visualizations/s02-tool-dispatch")),
  s03: lazy(() => import("@/components/visualizations/s03-todo-write")),
  s04: lazy(() => import("@/components/visualizations/s04-subagent")),
  s05: lazy(() => import("@/components/visualizations/s05-skill-loading")),
  s06: lazy(() => import("@/components/visualizations/s06-context-compact")),
  s07: lazy(() => import("@/components/visualizations/s07-task-system")),
  s08: lazy(() => import("@/components/visualizations/s08-background-tasks")),
  s09: lazy(() => import("@/components/visualizations/s09-agent-teams")),
  s10: lazy(() => import("@/components/visualizations/s10-team-protocols")),
  s11: lazy(() => import("@/components/visualizations/s11-autonomous-agents")),
  s12: lazy(() => import("@/components/visualizations/s12-worktree-task-isolation")),
};

// ─── Scenario loader ──────────────────────────────────────────────────────────
const scenarioModules: Record<string, () => Promise<{ default: Scenario }>> = {
  s01: () => import("@/data/scenarios/s01.json") as Promise<{ default: Scenario }>,
  s02: () => import("@/data/scenarios/s02.json") as Promise<{ default: Scenario }>,
  s03: () => import("@/data/scenarios/s03.json") as Promise<{ default: Scenario }>,
  s04: () => import("@/data/scenarios/s04.json") as Promise<{ default: Scenario }>,
  s05: () => import("@/data/scenarios/s05.json") as Promise<{ default: Scenario }>,
  s06: () => import("@/data/scenarios/s06.json") as Promise<{ default: Scenario }>,
  s07: () => import("@/data/scenarios/s07.json") as Promise<{ default: Scenario }>,
  s08: () => import("@/data/scenarios/s08.json") as Promise<{ default: Scenario }>,
  s09: () => import("@/data/scenarios/s09.json") as Promise<{ default: Scenario }>,
  s10: () => import("@/data/scenarios/s10.json") as Promise<{ default: Scenario }>,
  s11: () => import("@/data/scenarios/s11.json") as Promise<{ default: Scenario }>,
  s12: () => import("@/data/scenarios/s12.json") as Promise<{ default: Scenario }>,
};

// ─── Markdown ────────────────────────────────────────────────────────────────
function renderMarkdown(md: string): string {
  const result = unified()
    .use(remarkParse)
    .use(remarkGfm)
    .use(remarkRehype, { allowDangerousHtml: true })
    .use(rehypeRaw)
    .use(rehypeHighlight, { detect: false, ignoreMissing: true })
    .use(rehypeStringify)
    .processSync(md);
  return String(result);
}

// ─── Slide 1: Learning ───────────────────────────────────────────────────────
function SlideLearn({ version }: { version: string }) {
  const t = useTranslations("showcase");
  const tMeta = useTranslations("version_meta");
  const locale = useLocale();
  const meta = VERSION_META[version];

  // Prefer i18n translation; fall back to hardcoded English from VERSION_META
  const keyInsight = tMeta(`${version}_keyInsight`) || meta?.keyInsight;
  const coreAddition = tMeta(`${version}_coreAddition`) || meta?.coreAddition;

  const docEntry =
    docsData.find(
      (d: { version: string; locale: string }) =>
        d.version === version && d.locale === locale
    ) ||
    docsData.find(
      (d: { version: string; locale: string }) =>
        d.version === version && d.locale === "en"
    );

  const rawHtml = docEntry
    ? renderMarkdown((docEntry as { content: string }).content)
    : "";

  // Apply the same post-processing as DocRenderer (fixes ol counters, code blocks, etc.)
  function postProcessHtml(html: string): string {
    html = html.replace(
      /<pre><code class="hljs language-(\w+)">/g,
      '<pre class="code-block" data-language="$1"><code class="hljs language-$1">'
    );
    html = html.replace(
      /<pre><code(?! class="hljs)([^>]*)>/g,
      '<pre class="ascii-diagram"><code$1>'
    );
    html = html.replace(/<blockquote>/, '<blockquote class="hero-callout">');
    html = html.replace(/<h1[^>]*>.*?<\/h1>\n?/s, "");
    html = html.replace(
      /<ol start="(\d+)">/g,
      (_, start) => `<ol style="counter-reset:step-counter ${parseInt(start) - 1}">`
    );
    return html;
  }

  const cleanedHtml = rawHtml ? postProcessHtml(rawHtml) : "";

  return (
    <div className="mx-auto flex h-full w-full max-w-3xl flex-col gap-5 overflow-hidden px-6 py-6 sm:px-8">
      {/* Section label */}
      <div className="flex shrink-0 items-center gap-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-100 text-blue-600 dark:bg-blue-900/40 dark:text-blue-400">
          <BookOpen size={16} />
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-widest text-[var(--color-text-secondary)]">
            01 / 03 — {t("learning")}
          </p>
        </div>
      </div>

      {/* Cards row */}
      <div className="grid shrink-0 gap-3 sm:grid-cols-2">
        {keyInsight && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 dark:border-amber-900/40 dark:bg-amber-950/30">
            <div className="mb-2 flex items-center gap-2">
              <Lightbulb size={14} className="text-amber-600 dark:text-amber-400" />
              <span className="text-xs font-semibold text-amber-800 dark:text-amber-300">
                {t("key_insight")}
              </span>
            </div>
            <p className="text-sm leading-relaxed text-amber-900 dark:text-amber-200/80">
              {keyInsight}
            </p>
          </div>
        )}
        {coreAddition && (
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 dark:border-emerald-900/40 dark:bg-emerald-950/30">
            <div className="mb-2 flex items-center gap-2">
              <Plus size={14} className="text-emerald-600 dark:text-emerald-400" />
              <span className="text-xs font-semibold text-emerald-800 dark:text-emerald-300">
                {t("core_addition")}
              </span>
            </div>
            <p className="text-sm leading-relaxed text-emerald-900 dark:text-emerald-200/80">
              {coreAddition}
            </p>
          </div>
        )}
      </div>

      {/* Scrollable doc */}
      {cleanedHtml && (
        <div className="min-h-0 flex-1 overflow-y-auto rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-5 py-4">
          <div
            className="prose-custom"
            dangerouslySetInnerHTML={{ __html: cleanedHtml }}
          />
        </div>
      )}
    </div>
  );
}

// ─── Slide 2: Visualization ──────────────────────────────────────────────────
function SlideViz({ version }: { version: string }) {
  const t = useTranslations("showcase");
  const tViz = useTranslations("viz");
  const VizComponent = vizComponents[version];

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      {/* Section header */}
      <div className="shrink-0 border-b border-[var(--color-border)] px-6 py-4 sm:px-8">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
            <BarChart3 size={16} />
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-[var(--color-text-secondary)]">
              02 / 03 — {t("visualization")}
            </p>
          </div>
        </div>
      </div>

      {/* Viz content */}
      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4 sm:px-8">
        {VizComponent ? (
          <Suspense
            fallback={
              <div className="flex h-64 items-center justify-center">
                <div className="h-7 w-7 animate-spin rounded-full border-2 border-[var(--color-border)] border-t-blue-500" />
              </div>
            }
          >
            <VizComponent title={tViz(version)} />
          </Suspense>
        ) : (
          <div className="flex h-64 items-center justify-center text-[var(--color-text-secondary)]">
            No visualization available
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Slide 3: Simulator ──────────────────────────────────────────────────────
function SlideSimulator({ version }: { version: string }) {
  const t = useTranslations("showcase");
  const tSim = useTranslations("sim");
  const locale = useLocale();
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const loader = scenarioModules[version];
    if (loader) loader().then((mod) => setScenario(mod.default));
  }, [version]);

  const localizedScenario = (() => {
    if (!scenario) return null;
    if (locale !== "en") {
      const localeData = (scenario as unknown as Record<string, unknown>)[locale];
      if (localeData && typeof localeData === "object") {
        return { ...scenario, ...(localeData as Partial<Scenario>) };
      }
    }
    return scenario;
  })();

  const sim = useSimulator(localizedScenario?.steps ?? []);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [sim.visibleSteps.length]);

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      {/* Section header */}
      <div className="shrink-0 border-b border-[var(--color-border)] px-6 py-4 sm:px-8">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-100 text-emerald-600 dark:bg-emerald-900/40 dark:text-emerald-400">
            <Terminal size={16} />
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-[var(--color-text-secondary)]">
              03 / 03 — {t("simulator")}
            </p>
            {localizedScenario?.title && (
              <p className="text-sm font-medium text-[var(--color-text)]">
                {localizedScenario.title}
              </p>
            )}
          </div>
        </div>
      </div>

      {localizedScenario ? (
        <>
          {localizedScenario.description && (
            <div className="shrink-0 border-b border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-6 py-3 sm:px-8">
              <p className="text-sm text-[var(--color-text-secondary)]">
                {localizedScenario.description}
              </p>
            </div>
          )}
          {/* Controls */}
          <div className="shrink-0 border-b border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-6 py-3 sm:px-8">
            <SimulatorControls
              isPlaying={sim.isPlaying}
              isComplete={sim.isComplete}
              currentIndex={sim.currentIndex}
              totalSteps={sim.totalSteps}
              speed={sim.speed}
              onPlay={sim.play}
              onPause={sim.pause}
              onStep={sim.stepForward}
              onReset={sim.reset}
              onSpeedChange={sim.setSpeed}
            />
          </div>
          {/* Messages */}
          <div
            ref={scrollRef}
            className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-6 py-4 sm:px-8"
          >
            {sim.visibleSteps.length === 0 && (
              <div className="flex flex-1 items-center justify-center gap-2 text-sm text-[var(--color-text-secondary)]">
                <Play size={14} />
                {tSim("begin_hint")}
              </div>
            )}
            <AnimPresence mode="popLayout">
              {sim.visibleSteps.map((step, i) => (
                <SimulatorMessage key={i} step={step} index={i} />
              ))}
            </AnimPresence>
          </div>
        </>
      ) : (
        <div className="flex flex-1 items-center justify-center">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-[var(--color-border)] border-t-emerald-500" />
        </div>
      )}
    </div>
  );
}

// ─── Slide definitions ────────────────────────────────────────────────────────
type SlideId = "learn" | "viz" | "sim";

interface SlideDef {
  id: SlideId;
  icon: React.ElementType;
  labelKey: "learning" | "visualization" | "simulator";
  activeColor: string;
  iconBg: string;
}

const SLIDES: SlideDef[] = [
  {
    id: "learn",
    icon: BookOpen,
    labelKey: "learning",
    activeColor: "text-blue-600 dark:text-blue-400",
    iconBg: "bg-blue-100 text-blue-600 dark:bg-blue-900/40 dark:text-blue-400",
  },
  {
    id: "viz",
    icon: BarChart3,
    labelKey: "visualization",
    activeColor: "text-zinc-900 dark:text-zinc-100",
    iconBg: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300",
  },
  {
    id: "sim",
    icon: Terminal,
    labelKey: "simulator",
    activeColor: "text-emerald-600 dark:text-emerald-400",
    iconBg: "bg-emerald-100 text-emerald-600 dark:bg-emerald-900/40 dark:text-emerald-400",
  },
];

// ─── Slide animation variants ─────────────────────────────────────────────────
const slideVariants = {
  enter: (dir: number) => ({ x: dir > 0 ? "60%" : "-60%", opacity: 0 }),
  center: { x: 0, opacity: 1 },
  exit: (dir: number) => ({ x: dir < 0 ? "60%" : "-60%", opacity: 0 }),
};

// ─── Main ShowcasePPT ─────────────────────────────────────────────────────────
interface ShowcasePageProps {
  version: string;
}

export function ShowcasePPT({ version }: ShowcasePageProps) {
  const t = useTranslations("showcase");
  const tSession = useTranslations("sessions");
  const locale = useLocale();
  const meta = VERSION_META[version];

  const [slideIndex, setSlideIndex] = useState(0);
  const [direction, setDirection] = useState(0);
  const [isFullscreen, setIsFullscreen] = useState(false);

  const pathIndex = LEARNING_PATH.indexOf(version as (typeof LEARNING_PATH)[number]);
  const prevVersion = pathIndex > 0 ? LEARNING_PATH[pathIndex - 1] : null;
  const nextVersion =
    pathIndex < LEARNING_PATH.length - 1 ? LEARNING_PATH[pathIndex + 1] : null;

  const goSlide = useCallback(
    (next: number) => {
      setDirection(next > slideIndex ? 1 : -1);
      setSlideIndex(next);
    },
    [slideIndex]
  );

  const goNext = useCallback(() => {
    if (slideIndex < SLIDES.length - 1) goSlide(slideIndex + 1);
  }, [slideIndex, goSlide]);

  const goPrev = useCallback(() => {
    if (slideIndex > 0) goSlide(slideIndex - 1);
  }, [slideIndex, goSlide]);

  // Keyboard navigation
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if (e.key === "ArrowRight") goNext();
      else if (e.key === "ArrowLeft") goPrev();
      else if (e.key === "f" || e.key === "F") toggleFullscreen();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [goNext, goPrev]);

  const toggleFullscreen = useCallback(() => {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().catch(() => {});
    } else {
      document.exitFullscreen().catch(() => {});
    }
  }, []);

  useEffect(() => {
    const handler = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", handler);
    return () => document.removeEventListener("fullscreenchange", handler);
  }, []);

  // Reset slide on version change
  useEffect(() => {
    setSlideIndex(0);
    setDirection(0);
  }, [version]);

  return (
    <div className="flex flex-col">
      {/* ── Page header — mirrors standard page header ───────────────────── */}
      <div className="mb-6">
        {/* Breadcrumb */}
        <div className="mb-3 flex items-center gap-2 text-sm text-[var(--color-text-secondary)]">
          <Link
            href={`/${locale}/showcase`}
            className="flex items-center gap-1 hover:text-[var(--color-text)] hover:underline"
          >
            <LayoutGrid size={13} />
            <span>{t("all_tasks")}</span>
          </Link>
          <ChevronRight size={13} />
          <span className="font-mono text-xs">{version}</span>
          <span>{tSession(version) || meta?.title}</span>
        </div>

        {/* Version title row */}
        <div className="flex flex-wrap items-center gap-3">
          <span className="rounded-lg bg-zinc-100 px-3 py-1 font-mono text-lg font-bold dark:bg-zinc-800">
            {version}
          </span>
          <h1 className="text-2xl font-bold sm:text-3xl">
            {tSession(version) || meta?.title}
          </h1>
          {meta?.layer && (
            <LayerBadge layer={meta.layer}>
              {LAYERS.find((l) => l.id === meta.layer)?.label}
            </LayerBadge>
          )}
        </div>
        {meta?.subtitle && (
          <p className="mt-1 text-lg text-zinc-500 dark:text-zinc-400">
            {meta.subtitle}
          </p>
        )}

        {/* Task progress indicator */}
        <div className="mt-3 flex items-center gap-2">
          <div className="flex items-center gap-0.5">
            {LEARNING_PATH.map((vid, idx) => (
              <Link
                key={vid}
                href={`/${locale}/showcase/${vid}`}
                title={vid}
                className={cn(
                  "h-1.5 rounded-full transition-all",
                  vid === version
                    ? "w-5 bg-blue-500"
                    : idx < pathIndex
                      ? "w-1.5 bg-zinc-400 hover:bg-zinc-600 dark:bg-zinc-600 dark:hover:bg-zinc-400"
                      : "w-1.5 bg-zinc-200 hover:bg-zinc-400 dark:bg-zinc-800 dark:hover:bg-zinc-600"
                )}
              />
            ))}
          </div>
          <span className="font-mono text-xs text-[var(--color-text-secondary)]">
            {pathIndex + 1} / {LEARNING_PATH.length}
          </span>
          <button
            onClick={toggleFullscreen}
            title={isFullscreen ? t("exit_fullscreen") : t("enter_fullscreen")}
            className="ml-auto rounded-md p-1.5 text-[var(--color-text-secondary)] transition-colors hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
          >
            {isFullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>
        </div>
      </div>

      {/* ── Slide tabs ───────────────────────────────────────────────────── */}
      <div className="mb-0 flex rounded-t-xl border border-b-0 border-zinc-200 bg-zinc-50/80 dark:border-zinc-800 dark:bg-zinc-900/50">
        {SLIDES.map((slide, i) => {
          const Icon = slide.icon;
          const isActive = i === slideIndex;
          const isDone = i < slideIndex;
          return (
            <button
              key={slide.id}
              onClick={() => goSlide(i)}
              className={cn(
                "relative flex flex-1 items-center justify-center gap-2 px-4 py-3 text-sm font-medium transition-all",
                isActive
                  ? "bg-[var(--color-bg)] text-[var(--color-text)]"
                  : "text-[var(--color-text-secondary)] hover:text-[var(--color-text)]"
              )}
            >
              <Icon size={15} className={isActive ? slide.activeColor : ""} />
              <span>{t(slide.labelKey)}</span>
              {isDone && (
                <span className="ml-1 text-[10px] text-emerald-500">✓</span>
              )}
              {isActive && (
                <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-blue-500" />
              )}
            </button>
          );
        })}
      </div>

      {/* ── Slide content ───────────────────────────────────────────────── */}
      <div
        className="relative overflow-hidden rounded-b-xl border border-[var(--color-border)] bg-[var(--color-bg)]"
        style={{ minHeight: "560px" }}
      >
        <AnimatePresence mode="wait" custom={direction}>
          <motion.div
            key={slideIndex}
            custom={direction}
            variants={slideVariants}
            initial="enter"
            animate="center"
            exit="exit"
            transition={{
              x: { type: "spring", stiffness: 340, damping: 34 },
              opacity: { duration: 0.18 },
            }}
            className="absolute inset-0 overflow-hidden"
          >
            {slideIndex === 0 && <SlideLearn version={version} />}
            {slideIndex === 1 && <SlideViz version={version} />}
            {slideIndex === 2 && <SlideSimulator version={version} />}
          </motion.div>
        </AnimatePresence>
      </div>

      {/* ── Bottom navigation ───────────────────────────────────────────── */}
      <div className="mt-4 flex items-center justify-between border-t border-[var(--color-border)] pt-4">
        {/* Slide prev / next */}
        <div className="flex items-center gap-2">
          <button
            onClick={goPrev}
            disabled={slideIndex === 0}
            className="flex items-center gap-1 rounded-md px-3 py-1.5 text-sm text-[var(--color-text-secondary)] transition-colors hover:bg-zinc-100 hover:text-zinc-700 disabled:opacity-30 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
          >
            <ChevronLeft size={15} />
            {slideIndex > 0 ? t(SLIDES[slideIndex - 1].labelKey) : ""}
          </button>
          <button
            onClick={goNext}
            disabled={slideIndex === SLIDES.length - 1}
            className="flex items-center gap-1 rounded-md px-3 py-1.5 text-sm text-[var(--color-text-secondary)] transition-colors hover:bg-zinc-100 hover:text-zinc-700 disabled:opacity-30 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
          >
            {slideIndex < SLIDES.length - 1 ? t(SLIDES[slideIndex + 1].labelKey) : ""}
            <ChevronRight size={15} />
          </button>
        </div>

        {/* Task prev / next */}
        <div className="flex items-center gap-2">
          {prevVersion ? (
            <Link
              href={`/${locale}/showcase/${prevVersion}`}
              className="flex items-center gap-1 text-sm text-[var(--color-text-secondary)] hover:text-[var(--color-text)]"
            >
              <ChevronLeft size={14} />
              <span className="font-mono text-xs">{prevVersion}</span>
            </Link>
          ) : null}
          {nextVersion ? (
            <Link
              href={`/${locale}/showcase/${nextVersion}`}
              className="flex items-center gap-1 rounded-lg bg-zinc-900 px-4 py-1.5 text-sm font-medium text-white transition-colors hover:bg-zinc-700 dark:bg-white dark:text-zinc-900 dark:hover:bg-zinc-200"
            >
              <span className="font-mono text-xs">{nextVersion}</span>
              <ChevronRight size={14} />
            </Link>
          ) : null}
        </div>
      </div>
    </div>
  );
}
