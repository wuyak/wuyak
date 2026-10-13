import { mkdtemp, mkdir, rename, rm, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";

import { PacmanRenderer } from "pacman-contribution-graph";

const THEMES = [
  {
    name: "github",
    file: "pacman-light.svg",
    background: "#ebedf0",
  },
  {
    name: "github-dark",
    file: "pacman-dark.svg",
    background: "#161b22",
  },
];

function option(name, fallback) {
  const index = process.argv.indexOf(`--${name}`);
  if (index === -1) return fallback;
  const value = process.argv[index + 1];
  if (!value || value.startsWith("--")) {
    throw new Error(`--${name} requires a value`);
  }
  return value;
}

function contributionSnapshot(contributions) {
  return contributions
    .map(({ date, count, level }) => ({
      date: new Date(date).toISOString().slice(0, 10),
      count,
      level,
    }))
    .sort((a, b) => a.date.localeCompare(b.date));
}

function validateSvg(svg, theme, expectedActiveDays) {
  if (!svg.startsWith("<svg ") || !svg.endsWith("</svg>")) {
    throw new Error(`${theme.file} is not a complete SVG document`);
  }

  const cellBlocks = [
    ...svg.matchAll(/<rect id="(c-\d+-\d+)"[\s\S]*?<\/rect>/g),
  ];
  if (cellBlocks.length !== 53 * 7) {
    throw new Error(
      `${theme.file} has ${cellBlocks.length} contribution cells; expected 371`,
    );
  }

  const activeCells = cellBlocks.filter(([block]) => {
    const values = block.match(/values="([^"]+)"/)?.[1];
    return values?.split(";").some((color) => color !== theme.background);
  });
  if (expectedActiveDays === 0 || activeCells.length !== expectedActiveDays) {
    throw new Error(
      `${theme.file} has ${activeCells.length} active cells; expected ${expectedActiveDays}`,
    );
  }

  const frames = Number(svg.match(/<frames>(\d+)<\/frames>/)?.[1]);
  if (
    !Number.isInteger(frames) ||
    frames <= 1 ||
    !svg.includes('id="pacman"') ||
    !svg.includes("<animateTransform")
  ) {
    throw new Error(`${theme.file} does not contain a complete animation`);
  }

  return { activeCells: activeCells.length, frames };
}

async function render({ username, token, theme }) {
  let svg = "";
  const renderer = new PacmanRenderer({
    platform: "github",
    username,
    gameTheme: theme.name,
    githubSettings: { accessToken: token },
    svgCallback: (value) => {
      svg = value;
    },
  });
  const store = await renderer.start();
  if (!svg) throw new Error(`${theme.file} renderer returned no SVG`);
  return { svg, store };
}

async function main() {
  const username = option("username", process.env.GITHUB_REPOSITORY_OWNER);
  const outputDir = resolve(option("output-dir", "assets"));
  const token = process.env.GITHUB_TOKEN;

  if (!username || !/^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$/.test(username)) {
    throw new Error(
      "Provide a valid GitHub login with --username or GITHUB_REPOSITORY_OWNER",
    );
  }
  if (!token) {
    throw new Error("GITHUB_TOKEN is required for GitHub GraphQL contribution data");
  }

  const rendered = [];
  for (const theme of THEMES) {
    rendered.push({ theme, ...(await render({ username, token, theme })) });
  }

  const snapshots = rendered.map(({ store }) =>
    contributionSnapshot(store.contributions),
  );
  if (JSON.stringify(snapshots[0]) !== JSON.stringify(snapshots[1])) {
    throw new Error("GitHub contribution data changed between theme renders");
  }
  const activeDays = snapshots[0].filter(({ count }) => count > 0).length;
  const totalContributions = snapshots[0].reduce(
    (total, { count }) => total + count,
    0,
  );

  const results = rendered.map(({ svg, theme }) => ({
    theme,
    svg,
    ...validateSvg(svg, theme, activeDays),
  }));

  await mkdir(outputDir, { recursive: true });
  const stagingDir = await mkdtemp(join(outputDir, ".pacman-staging-"));
  try {
    for (const { theme, svg } of results) {
      await writeFile(join(stagingDir, theme.file), svg, "utf8");
    }
    for (const { theme } of results) {
      await rename(join(stagingDir, theme.file), join(outputDir, theme.file));
    }
  } finally {
    await rm(stagingDir, { recursive: true, force: true });
  }

  for (const { theme, svg, activeCells, frames } of results) {
    console.log(
      `${theme.file}: ${Buffer.byteLength(svg)} bytes, ${frames} frames, ${activeCells} animated contribution cells`,
    );
  }
  console.log(
    `GitHub contribution calendar: ${activeDays} active days, ${totalContributions} contributions`,
  );
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
