import { LEARNING_PATH } from "@/lib/constants";
import ShowcaseVersionClient from "./client";

export function generateStaticParams() {
  return LEARNING_PATH.map((version) => ({ version }));
}

export default function ShowcaseVersionPage() {
  return <ShowcaseVersionClient />;
}
