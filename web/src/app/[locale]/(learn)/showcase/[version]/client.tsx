"use client";

import { useParams } from "next/navigation";
import { useLocale } from "@/lib/i18n";
import { VERSION_META } from "@/lib/constants";
import { ShowcasePPT } from "@/components/showcase/showcase-slide";
import Link from "next/link";

export default function ShowcaseVersionClient() {
  const params = useParams();
  const locale = useLocale();
  const version = (params?.version as string) || "s01";
  const meta = VERSION_META[version];

  if (!meta) {
    return (
      <div className="py-20 text-center">
        <p className="text-xl font-bold">Version not found: {version}</p>
        <Link
          href={`/${locale}/showcase`}
          className="mt-4 inline-block text-blue-600 hover:underline dark:text-blue-400"
        >
          ← Back to Showcase
        </Link>
      </div>
    );
  }

  return <ShowcasePPT version={version} />;
}
