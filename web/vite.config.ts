import { defineConfig } from "vite";

// Relative paths, so the build also works from a sub-folder on the judges' link.
// Builds to build/, because dist/ holds the team's hosted page.
export default defineConfig({ base: "./", build: { outDir: "build" } });
