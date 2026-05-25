#!/usr/bin/env node
/**
 * linear-bootstrap.js
 * Auto-creates ClawdianShield initial backlog in Linear from module tree.
 *
 * Usage:
 *   Add your key to .env as LINEAR_API_KEY=<your_key>, then:
 *   node scripts/linear-bootstrap.js
 *
 * Get your API key: Linear → Settings → API → Personal API keys
 */

import "dotenv/config";
import { LinearClient } from "@linear/sdk";

const LINEAR_API_KEY = process.env.LINEAR_API_KEY;
if (!LINEAR_API_KEY) {
  console.error("Missing LINEAR_API_KEY env var");
  process.exit(1);
}

const client = new LinearClient({ apiKey: LINEAR_API_KEY });

// Canonical backlog — no duplicates, single owner per issue
const BACKLOG = [
  {
    milestone: "MVP Baseline",
    label: "tests",
    issues: [
      "[tests] Add test harness for collectors",
      "[tests] Add unit tests for stat snapshot diffing",
    ],
  },
  {
    milestone: "MVP Baseline",
    label: "automation",
    issues: [
      "[automation] Set up milestone board for MVP",
      "[automation] Create GitHub issue/PR linking convention",
      "[automation] Wire GitHub PRs to Linear issues",
    ],
  },
  {
    milestone: "Telemetry",
    label: "telemetry",
    issues: [
      "[telemetry] Build FIM collector validation workflow",
      "[telemetry] Implement telemetry collector interfaces",
      "[telemetry] Define collector output schema",
      "[telemetry] Validate FIM events against .env tamper cases",
    ],
  },
  {
    milestone: "Detections",
    label: "detections",
    issues: [
      "[detections] Add detection scenarios for file tampering",
      "[detections] Add evidence mapping for detections",
    ],
  },
  {
    milestone: "Scenarios",
    label: "victim",
    issues: [
      "[victim] Create seeded developer workstation artifacts",
      "[victim] Add FIM demo validation steps",
    ],
  },
  {
    milestone: "Evidence",
    label: "utils",
    issues: [
      "[utils] Build evidence output structure",
      "[utils] Capture screenshots for evidence",
    ],
  },
  {
    milestone: "Portfolio Packaging",
    label: "docs",
    issues: [
      "[docs] Write telemetry architecture and data flow",
      "[docs] Document collector output schema",
    ],
  },
];

async function bootstrap() {
  // Get the team
  const teams = await client.teams();
  const team = teams.nodes[0];
  if (!team) {
    console.error("No Linear team found. Create one at linear.app first.");
    process.exit(1);
  }
  console.log(`Using team: ${team.name} (${team.id})`);

  // Get or create the project
  const projects = await client.projects();
  let project = projects.nodes.find((p) => p.name === "ClawdianShield");
  if (!project) {
    const created = await client.createProject({
      name: "ClawdianShield",
      teamIds: [team.id],
    });
    project = created.project;
    console.log(`Created project: ClawdianShield`);
  } else {
    console.log(`Found project: ClawdianShield`);
  }

  // Get existing labels
  const labelsResult = await team.labels();
  const labelMap = Object.fromEntries(
    labelsResult.nodes.map((l) => [l.name.toLowerCase(), l.id])
  );

  // Fetch existing issue titles to avoid duplicates
  const existing = await client.issues({ filter: { project: { id: { eq: project.id } } } });
  const existingTitles = new Set(existing.nodes.map((i) => i.title));

  // Create issues
  let created = 0;
  let skipped = 0;
  for (const group of BACKLOG) {
    for (const title of group.issues) {
      if (existingTitles.has(title)) {
        console.log(`  ⏭ skip (exists): ${title}`);
        skipped++;
        continue;
      }
      const labelId = labelMap[group.label];
      await client.createIssue({
        teamId: team.id,
        projectId: project.id,
        title,
        ...(labelId ? { labelIds: [labelId] } : {}),
        description: `Milestone: ${group.milestone}`,
      });
      console.log(`  ✓ [${group.label}] ${title}`);
      created++;
    }
  }
  console.log(`\nCreated: ${created}  Skipped: ${skipped}`);

  console.log("\nBacklog bootstrap complete.");
}

bootstrap().catch((err) => {
  console.error(err);
  process.exit(1);
});
