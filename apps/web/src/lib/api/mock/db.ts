/**
 * DEV-ONLY seed data for mock mode (NEXT_PUBLIC_API_MODE=mock).
 * Shapes follow @apppilot/contracts so screens are built against the
 * draft contract, not against this data.
 */
import type {
  ActivityEvent,
  AdminAuditEvent,
  AdminUser,
  AgentTask,
  AgentTimelineEvent,
  Artifact,
  Build,
  ChangeSet,
  ChatMessage,
  Diagnostic,
  GitCommit,
  GitFileStatus,
  Invoice,
  Plan,
  Project,
  ProjectEnvVar,
  Subscription,
  TestCase,
  TestJob,
  TestScreenshot,
  UploadSession,
  User,
  UserPreferences,
  WorkerStatus,
} from "@apppilot/contracts";
import { SAMPLE_CHANGE, SAMPLE_FILES } from "./sample-project";
import { getActiveSession, seedDemoUsersIfEmpty, toSessionUser } from "./demo-auth-store";

const NOW = Date.now();
export const ago = (min: number) => new Date(NOW - min * 60_000).toISOString();

export interface MockFile {
  content: string;
  version: string;
  gitStatus: GitFileStatus | null;
  aiModified: boolean;
  aiRanges: { startLine: number; endLine: number; taskId: string }[];
}

let versionCounter = 1;
export const nextVersion = () => `v${versionCounter++}`;

const file = (content: string, extra: Partial<MockFile> = {}): MockFile => ({
  content,
  version: nextVersion(),
  gitStatus: null,
  aiModified: false,
  aiRanges: [],
  ...extra,
});

function filesFrom(record: Record<string, string>): Map<string, MockFile> {
  return new Map(Object.entries(record).map(([p, c]) => [p, file(c)]));
}

const user: User = {
  id: "u_1",
  name: "Mira Kapoor",
  email: "mira@example.dev",
  avatarUrl: null,
  role: "admin",
  emailVerified: true,
  createdAt: ago(60 * 24 * 90),
};

// Demo auth (frontend-only, see ./demo-auth-store): start signed out unless a
// persisted demo session says otherwise, so the real login/signup flow runs.
seedDemoUsersIfEmpty();
const activeDemoSession = getActiveSession();

const trailFiles = filesFrom(SAMPLE_FILES);
// Mark an earlier agent edit so AI indicators are visible.
const repo = trailFiles.get("app/src/main/java/com/trailhead/app/data/TrailRepository.kt");
if (repo) {
  repo.aiModified = true;
  repo.gitStatus = "modified";
  repo.aiRanges = [{ startLine: 21, endLine: 22, taskId: "t_0" }];
}
const strings = trailFiles.get("app/src/main/res/values/strings.xml");
if (strings) strings.gitStatus = "modified";

const projects: Project[] = [
  {
    id: "p_trailhead",
    name: "Trailhead",
    description: "Compose app listing nearby hiking trails with offline maps.",
    source: "prompt",
    status: "ready",
    language: "kotlin",
    uiToolkit: "compose",
    packageName: "com.trailhead.app",
    minSdk: 26,
    targetSdk: 35,
    isApkAnalysis: false,
    activeTaskCount: 1,
    lastBuild: { id: "b_14", status: "running", finishedAt: null },
    storageBytes: 48_300_000,
    createdAt: ago(60 * 24 * 12),
    updatedAt: ago(4),
  },
  {
    id: "p_ledgerly",
    name: "Ledgerly",
    description: "Expense tracker imported from an Android Studio project (Java, XML views).",
    source: "android_zip",
    status: "ready",
    language: "java",
    uiToolkit: "xml",
    packageName: "io.ledgerly",
    minSdk: 24,
    targetSdk: 34,
    isApkAnalysis: false,
    activeTaskCount: 0,
    lastBuild: { id: "b_9", status: "failed", finishedAt: ago(180) },
    storageBytes: 112_000_000,
    createdAt: ago(60 * 24 * 30),
    updatedAt: ago(170),
  },
  {
    id: "p_weather",
    name: "WeatherPro (APK)",
    description: "Analysis of weatherpro-2.4.1.apk.",
    source: "apk",
    status: "ready",
    language: "java",
    uiToolkit: "xml",
    packageName: "com.example.weatherpro",
    minSdk: 23,
    targetSdk: 33,
    isApkAnalysis: true,
    activeTaskCount: 0,
    lastBuild: null,
    storageBytes: 21_700_000,
    createdAt: ago(60 * 24 * 3),
    updatedAt: ago(60 * 24 * 3),
  },
  {
    id: "p_pantry",
    name: "Pantry Pal",
    description: "Grocery list app with barcode scanning and shared lists.",
    source: "prompt",
    status: "creating",
    language: "kotlin",
    uiToolkit: "compose",
    packageName: "app.pantrypal",
    minSdk: 26,
    targetSdk: 35,
    isApkAnalysis: false,
    activeTaskCount: 1,
    lastBuild: null,
    storageBytes: 0,
    createdAt: ago(6),
    updatedAt: ago(1),
  },
];

const task = (t: Partial<AgentTask> & Pick<AgentTask, "id" | "projectId" | "title" | "status">): AgentTask => ({
  description: "",
  intent: "modify",
  currentStep: null,
  filesAnalyzing: [],
  filesModifying: [],
  buildProgress: null,
  repairIterations: 0,
  maxRepairIterations: 5,
  tokenUsage: { inputTokens: 0, outputTokens: 0 },
  recordedCostUsd: 0,
  blockedReason: null,
  errorMessage: null,
  createdAt: ago(30),
  startedAt: ago(29),
  finishedAt: null,
  ...t,
});

const tasks: AgentTask[] = [
  task({
    id: "t_2",
    projectId: "p_trailhead",
    title: "Fix R8 warning in release build",
    description: "Release build warns about missing keep rules for data classes. Fix and verify the build.",
    intent: "fix",
    status: "repairing",
    currentStep: "Rebuilding :app:assembleRelease after adding keep rule",
    filesAnalyzing: ["app/proguard-rules.pro", "app/build.gradle.kts"],
    filesModifying: ["app/proguard-rules.pro"],
    buildProgress: { percent: 62, phase: ":app:minifyReleaseWithR8" },
    repairIterations: 2,
    tokenUsage: { inputTokens: 48_210, outputTokens: 6_930 },
    recordedCostUsd: 0.41,
    createdAt: ago(18),
    startedAt: ago(17),
  }),
  task({
    id: "t_1",
    projectId: "p_trailhead",
    title: "Add trail search",
    description: "Add a search bar above the trail list that filters by name.",
    status: "completed",
    tokenUsage: { inputTokens: 31_400, outputTokens: 4_120 },
    recordedCostUsd: 0.27,
    createdAt: ago(55),
    startedAt: ago(54),
    finishedAt: ago(41),
  }),
  task({
    id: "t_3",
    projectId: "p_pantry",
    title: "Generate Pantry Pal",
    description: "Create a Compose app with shared grocery lists and barcode scanning.",
    intent: "generate",
    status: "generating",
    currentStep: "Writing feature/lists/ListDetailScreen.kt",
    filesAnalyzing: [],
    filesModifying: ["feature/lists/ListDetailScreen.kt", "feature/lists/ListViewModel.kt"],
    tokenUsage: { inputTokens: 12_800, outputTokens: 18_450 },
    recordedCostUsd: 0.36,
    createdAt: ago(6),
    startedAt: ago(5),
  }),
  task({
    id: "t_4",
    projectId: "p_ledgerly",
    title: "Migrate to ViewBinding",
    description: "Replace findViewById calls with ViewBinding across activities.",
    intent: "refactor",
    status: "failed",
    repairIterations: 5,
    errorMessage: "Build still failing after 5 repair attempts: unresolved reference ActivityMainBinding.",
    tokenUsage: { inputTokens: 92_000, outputTokens: 15_300 },
    recordedCostUsd: 0.88,
    createdAt: ago(240),
    startedAt: ago(239),
    finishedAt: ago(181),
  }),
  task({
    id: "t_5",
    projectId: "p_ledgerly",
    title: "Upgrade Android Gradle Plugin to 8.7",
    description: "Bump AGP and fix deprecations.",
    status: "blocked",
    blockedReason: "Release signing config references a keystore that isn't uploaded. Add it in Project settings → Environment.",
    tokenUsage: { inputTokens: 8_300, outputTokens: 900 },
    recordedCostUsd: 0.06,
    createdAt: ago(300),
    startedAt: ago(299),
    finishedAt: ago(296),
  }),
  task({
    id: "t_6",
    projectId: "p_trailhead",
    title: "Explain TrailRepository",
    intent: "explain",
    status: "cancelled",
    createdAt: ago(600),
    startedAt: ago(600),
    finishedAt: ago(599),
  }),
];

const tl = (taskId: string, minAgo: number, status: AgentTask["status"], title: string, detail?: string, files?: string[]): AgentTimelineEvent => ({
  id: `${taskId}_${minAgo}_${status}`,
  taskId,
  at: ago(minAgo),
  status,
  title,
  detail,
  files,
});

const timelines: Record<string, AgentTimelineEvent[]> = {
  t_2: [
    tl("t_2", 17, "queued", "Task queued"),
    tl("t_2", 17, "planning", "Planned 3 steps", "Inspect R8 output, add keep rules, rebuild release."),
    tl("t_2", 16, "analyzing", "Read build configuration", undefined, ["app/build.gradle.kts", "app/proguard-rules.pro"]),
    tl("t_2", 14, "generating", "Added keep rule for data package", undefined, ["app/proguard-rules.pro"]),
    tl("t_2", 13, "building", "Started :app:assembleRelease"),
    tl("t_2", 9, "repairing", "Repair 1: R8 still reports missing class", "Missing rule for kotlinx.serialization descriptors."),
    tl("t_2", 5, "repairing", "Repair 2: added serialization rules, rebuilding"),
  ],
  t_1: [
    tl("t_1", 54, "planning", "Planned 2 steps"),
    tl("t_1", 52, "analyzing", "Read TrailListScreen.kt", undefined, [SAMPLE_CHANGE.modifiedPath]),
    tl("t_1", 48, "generating", "Proposed TrailSearchBar.kt and list filtering", undefined, [SAMPLE_CHANGE.modifiedPath, SAMPLE_CHANGE.addedPath]),
    tl("t_1", 45, "building", "Debug build passed"),
    tl("t_1", 42, "testing", "Unit tests passed (2/2)"),
    tl("t_1", 41, "completed", "Changes ready for review"),
  ],
  t_3: [
    tl("t_3", 5, "planning", "Planned 9 steps", "Modules: app, feature/lists, feature/scan, data."),
    tl("t_3", 4, "generating", "Created Gradle setup and app module"),
    tl("t_3", 2, "generating", "Writing feature/lists"),
  ],
  t_4: [
    tl("t_4", 239, "planning", "Planned 6 steps"),
    tl("t_4", 220, "building", "Build failed: unresolved reference"),
    tl("t_4", 200, "repairing", "Repair attempts 1–4 failed"),
    tl("t_4", 181, "failed", "Stopped after 5 repair attempts"),
  ],
  t_5: [tl("t_5", 299, "analyzing", "Read signing config"), tl("t_5", 296, "blocked", "Missing release keystore")],
  t_6: [tl("t_6", 599, "cancelled", "Cancelled by user")],
};

const originalScreen = SAMPLE_FILES[SAMPLE_CHANGE.modifiedPath] ?? "";
const changeSets: ChangeSet[] = [
  {
    id: "cs_1",
    taskId: "t_1",
    summary: "Adds a search field that filters the trail list by name.",
    status: "pending",
    files: [
      {
        path: SAMPLE_CHANGE.modifiedPath,
        changeType: "modify",
        originalContent: originalScreen,
        proposedContent: SAMPLE_CHANGE.modify(originalScreen),
        decision: "pending",
      },
      {
        path: SAMPLE_CHANGE.addedPath,
        changeType: "add",
        originalContent: null,
        proposedContent: SAMPLE_CHANGE.addedContent,
        decision: "pending",
      },
    ],
  },
];

const messages: Record<string, ChatMessage[]> = {
  p_trailhead: [
    {
      id: "m_1",
      role: "user",
      content: "Add a search bar above the trail list that filters by trail name.",
      intent: "modify",
      createdAt: ago(55),
    },
    {
      id: "m_2",
      role: "assistant",
      content: "I'll add a reusable search field and filter the list in place. The debug build and unit tests pass with the change.",
      createdAt: ago(41),
      taskId: "t_1",
      plan: {
        summary: "Two-file change, no new dependencies.",
        steps: [
          { id: "s1", title: "Create TrailSearchBar", detail: "OutlinedTextField bound to a query string, hint from strings.xml.", files: [SAMPLE_CHANGE.addedPath] },
          { id: "s2", title: "Filter TrailListScreen", detail: "Hold query in remember{} state and filter trails by name.", files: [SAMPLE_CHANGE.modifiedPath] },
        ],
      },
      changeSetId: "cs_1",
    },
  ],
};

const build = (b: Partial<Build> & Pick<Build, "id" | "projectId" | "number" | "status">): Build => ({
  outputType: "apk",
  variant: "debug",
  gradleTask: ":app:assembleDebug",
  commitSha: "a1b2c3d",
  triggeredBy: "user",
  agentTaskId: null,
  queuedAt: ago(60),
  startedAt: ago(60),
  finishedAt: ago(58),
  durationMs: 128_000,
  errorSummary: null,
  errors: [],
  artifactIds: [],
  ...b,
});

const builds: Build[] = [
  build({
    id: "b_14", projectId: "p_trailhead", number: 14, status: "running", variant: "release",
    gradleTask: ":app:assembleRelease", triggeredBy: "agent", agentTaskId: "t_2",
    queuedAt: ago(5), startedAt: ago(5), finishedAt: null, durationMs: null, commitSha: "f04e9a2",
  }),
  build({
    id: "b_13", projectId: "p_trailhead", number: 13, status: "failed", outputType: "aab", variant: "release",
    gradleTask: ":app:bundleRelease", triggeredBy: "agent", agentTaskId: "t_2",
    queuedAt: ago(13), startedAt: ago(13), finishedAt: ago(10), durationMs: 171_000, commitSha: "c9d1e07",
    errorSummary: "R8: Missing class kotlinx.serialization.KSerializer",
    errors: [
      { path: "app/proguard-rules.pro", line: 1, column: 1, severity: "error", message: "Missing class kotlinx.serialization.KSerializer (referenced from com.trailhead.app.data.Trail)", task: ":app:minifyReleaseWithR8" },
      { path: "app/build.gradle.kts", line: 22, column: 13, severity: "warning", message: "isMinifyEnabled without shrinkResources leaves unused resources in the bundle", task: ":app:lintVitalRelease" },
    ],
  }),
  build({
    id: "b_12", projectId: "p_trailhead", number: 12, status: "succeeded",
    queuedAt: ago(46), startedAt: ago(46), finishedAt: ago(45), durationMs: 74_000, triggeredBy: "agent", agentTaskId: "t_1",
    artifactIds: ["a_12_apk"],
  }),
  build({
    id: "b_11", projectId: "p_trailhead", number: 11, status: "succeeded", outputType: "aab", variant: "release",
    gradleTask: ":app:bundleRelease", queuedAt: ago(60 * 26), startedAt: ago(60 * 26), finishedAt: ago(60 * 26 - 3), durationMs: 182_000,
    artifactIds: ["a_11_aab", "a_11_map"],
  }),
  build({
    id: "b_10", projectId: "p_trailhead", number: 10, status: "cancelled",
    queuedAt: ago(60 * 30), startedAt: ago(60 * 30), finishedAt: ago(60 * 30 - 1), durationMs: 21_000,
  }),
  build({
    id: "b_9", projectId: "p_ledgerly", number: 9, status: "failed", queuedAt: ago(184), startedAt: ago(184), finishedAt: ago(180),
    durationMs: 233_000, triggeredBy: "agent", agentTaskId: "t_4",
    errorSummary: "Compilation failed: unresolved reference ActivityMainBinding",
    errors: [{ path: "app/src/main/java/io/ledgerly/MainActivity.java", line: 18, column: 9, severity: "error", message: "cannot find symbol: class ActivityMainBinding", task: ":app:compileDebugJavaWithJavac" }],
  }),
  build({
    id: "b_8", projectId: "p_ledgerly", number: 8, status: "succeeded", queuedAt: ago(60 * 50), startedAt: ago(60 * 50), finishedAt: ago(60 * 49), durationMs: 96_000,
    artifactIds: ["a_8_apk"],
  }),
];

const artifacts: Artifact[] = [
  { id: "a_12_apk", projectId: "p_trailhead", buildId: "b_12", kind: "apk", fileName: "trailhead-0.3.0-debug.apk", sizeBytes: 9_840_000, sha256: "3f9c…a21e", createdAt: ago(45), expiresAt: null },
  { id: "a_11_aab", projectId: "p_trailhead", buildId: "b_11", kind: "aab", fileName: "trailhead-0.3.0-release.aab", sizeBytes: 6_120_000, sha256: "9b0d…77c4", createdAt: ago(60 * 26), expiresAt: null },
  { id: "a_11_map", projectId: "p_trailhead", buildId: "b_11", kind: "mapping", fileName: "mapping.txt", sizeBytes: 1_430_000, sha256: "11ae…0f3b", createdAt: ago(60 * 26), expiresAt: null },
  { id: "a_8_apk", projectId: "p_ledgerly", buildId: "b_8", kind: "apk", fileName: "ledgerly-1.8.2-debug.apk", sizeBytes: 12_400_000, sha256: "aa31…5d90", createdAt: ago(60 * 49), expiresAt: null },
];

const testJobs: TestJob[] = [
  { id: "tj_4", projectId: "p_trailhead", buildId: "b_12", kind: "unit", state: "finished", result: "passed", summary: { passed: 2, failed: 0, blocked: 0, unverified: 0, skipped: 0 }, device: null, startedAt: ago(44), finishedAt: ago(43), durationMs: 18_400, triggeredBy: "agent" },
  { id: "tj_3", projectId: "p_trailhead", buildId: "b_12", kind: "emulator", state: "finished", result: "unverified", summary: { passed: 3, failed: 0, blocked: 0, unverified: 1, skipped: 0 }, device: { name: "Pixel 8", apiLevel: 34, abi: "x86_64" }, startedAt: ago(43), finishedAt: ago(40), durationMs: 162_000, triggeredBy: "agent" },
  { id: "tj_2", projectId: "p_trailhead", buildId: "b_13", kind: "instrumentation", state: "finished", result: "blocked", summary: { passed: 0, failed: 0, blocked: 4, unverified: 0, skipped: 0 }, device: { name: "Pixel 6", apiLevel: 33, abi: "x86_64" }, startedAt: ago(10), finishedAt: ago(10), durationMs: 2_100, triggeredBy: "agent" },
  { id: "tj_1", projectId: "p_trailhead", buildId: "b_11", kind: "unit", state: "finished", result: "failed", summary: { passed: 1, failed: 1, blocked: 0, unverified: 0, skipped: 1 }, device: null, startedAt: ago(60 * 26), finishedAt: ago(60 * 26 - 1), durationMs: 21_000, triggeredBy: "user" },
];

const testCases: Record<string, TestCase[]> = {
  tj_4: [
    { id: "c1", jobId: "tj_4", suite: "TrailRepositoryTest", name: "searchIsCaseInsensitive", status: "passed", durationMs: 12, failureMessage: null, stackTrace: null },
    { id: "c2", jobId: "tj_4", suite: "TrailRepositoryTest", name: "searchWithNoMatchReturnsEmpty", status: "passed", durationMs: 4, failureMessage: null, stackTrace: null },
  ],
  tj_3: [
    { id: "c3", jobId: "tj_3", suite: "TrailListFlow", name: "launchShowsTrailList", status: "passed", durationMs: 4_200, failureMessage: null, stackTrace: null },
    { id: "c4", jobId: "tj_3", suite: "TrailListFlow", name: "typingFiltersList", status: "passed", durationMs: 6_900, failureMessage: null, stackTrace: null },
    { id: "c5", jobId: "tj_3", suite: "TrailListFlow", name: "scrollToLastTrail", status: "passed", durationMs: 3_100, failureMessage: null, stackTrace: null },
    { id: "c6", jobId: "tj_3", suite: "TrailListFlow", name: "locationPermissionPrompt", status: "unverified", durationMs: null, failureMessage: "Emulator image has no location provider; permission dialog could not be confirmed.", stackTrace: null },
  ],
  tj_2: ["opensDetail", "backReturnsToList", "rotationKeepsQuery", "emptyStateShown"].map((n, i) => ({
    id: `c2_${i}`, jobId: "tj_2", suite: "TrailListInstrumentedTest", name: n, status: "blocked" as const, durationMs: null,
    failureMessage: "Not run: build #13 failed, so no APK was available to install.", stackTrace: null,
  })),
  tj_1: [
    { id: "c7", jobId: "tj_1", suite: "TrailRepositoryTest", name: "searchIsCaseInsensitive", status: "failed", durationMs: 15, failureMessage: "expected:<1> but was:<0>", stackTrace: "java.lang.AssertionError: expected:<1> but was:<0>\n\tat org.junit.Assert.fail(Assert.java:89)\n\tat com.trailhead.app.data.TrailRepositoryTest.searchIsCaseInsensitive(TrailRepositoryTest.kt:11)" },
    { id: "c8", jobId: "tj_1", suite: "TrailRepositoryTest", name: "searchWithNoMatchReturnsEmpty", status: "passed", durationMs: 3, failureMessage: null, stackTrace: null },
    { id: "c9", jobId: "tj_1", suite: "DistanceFormatterTest", name: "formatsMetres", status: "skipped", durationMs: null, failureMessage: "@Ignore", stackTrace: null },
  ],
};

const phoneSvg = (label: string, accent: string) =>
  `data:image/svg+xml;utf8,${encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="270" height="560" viewBox="0 0 270 560"><rect width="270" height="560" rx="18" fill="#1b1f27"/><rect x="0" y="0" width="270" height="56" fill="${accent}"/><text x="16" y="36" font-family="sans-serif" font-size="16" fill="#fff">Trailhead</text>${[0, 1, 2, 3, 4].map((i) => `<rect x="16" y="${80 + i * 72}" width="238" height="56" rx="8" fill="#262c38"/><rect x="28" y="${94 + i * 72}" width="${120 + ((i * 37) % 80)}" height="10" rx="4" fill="#cfd6e4"/><rect x="28" y="${112 + i * 72}" width="80" height="8" rx="4" fill="#7f8aa0"/>`).join("")}<text x="16" y="540" font-family="monospace" font-size="11" fill="#7f8aa0">${label}</text></svg>`,
  )}`;

const screenshots: Record<string, TestScreenshot[]> = {
  tj_3: [
    { id: "s1", jobId: "tj_3", testCaseId: "c3", url: phoneSvg("launchShowsTrailList", "#2f5d50"), caption: "Launch", takenAt: ago(42) },
    { id: "s2", jobId: "tj_3", testCaseId: "c4", url: phoneSvg("typingFiltersList", "#2f5d50"), caption: "Filtered by “cedar”", takenAt: ago(41) },
    { id: "s3", jobId: "tj_3", testCaseId: "c5", url: phoneSvg("scrollToLastTrail", "#2f5d50"), caption: "Scrolled to end", takenAt: ago(41) },
  ],
};

const plans: Plan[] = [
  { id: "free", name: "Free", priceMonthlyUsd: 0, limits: { aiTokensPerMonth: 200_000, buildMinutesPerMonth: 60, storageBytes: 1_073_741_824, projects: 2, concurrentAgentTasks: 1 }, features: ["Debug builds", "Unit tests", "Community support"] },
  { id: "pro", name: "Pro", priceMonthlyUsd: 29, limits: { aiTokensPerMonth: 3_000_000, buildMinutesPerMonth: 600, storageBytes: 21_474_836_480, projects: 20, concurrentAgentTasks: 3 }, features: ["Release builds (APK + AAB)", "Emulator tests with screenshots", "APK analysis"] },
  { id: "team", name: "Team", priceMonthlyUsd: 99, limits: { aiTokensPerMonth: 15_000_000, buildMinutesPerMonth: 3000, storageBytes: 107_374_182_400, projects: null, concurrentAgentTasks: 10 }, features: ["Everything in Pro", "Shared projects", "Priority build queue", "Audit log"] },
];

const subscription: Subscription = { planId: "pro", status: "active", currentPeriodEnd: new Date(NOW + 12 * 86_400_000).toISOString(), cancelAtPeriodEnd: false };

const invoices: Invoice[] = [0, 1, 2, 3].map((i) => ({
  id: `in_${i}`,
  issuedAt: new Date(NOW - (18 + i * 30) * 86_400_000).toISOString(),
  amountUsd: 29,
  status: "paid",
  pdfUrl: null,
}));

const activity: ActivityEvent[] = [
  { id: "e1", projectId: "p_trailhead", projectName: "Trailhead", kind: "agent_task_started", message: "Agent started “Fix R8 warning in release build”", at: ago(17) },
  { id: "e2", projectId: "p_trailhead", projectName: "Trailhead", kind: "build_failed", message: "Build #13 failed (release AAB)", at: ago(10) },
  { id: "e3", projectId: "p_pantry", projectName: "Pantry Pal", kind: "project_created", message: "Project created from a prompt", at: ago(6) },
  { id: "e4", projectId: "p_trailhead", projectName: "Trailhead", kind: "agent_task_completed", message: "“Add trail search” is ready for review", at: ago(41) },
  { id: "e5", projectId: "p_trailhead", projectName: "Trailhead", kind: "build_succeeded", message: "Build #12 succeeded (debug APK)", at: ago(45) },
  { id: "e6", projectId: "p_ledgerly", projectName: "Ledgerly", kind: "agent_task_failed", message: "“Migrate to ViewBinding” failed after 5 repairs", at: ago(181) },
  { id: "e7", projectId: "p_weather", projectName: "WeatherPro (APK)", kind: "project_created", message: "APK analysis finished", at: ago(60 * 24 * 3) },
].sort((a, b) => b.at.localeCompare(a.at)) as ActivityEvent[];

const diagnostics: Diagnostic[] = [
  { path: "app/proguard-rules.pro", line: 1, column: 1, severity: "error", message: "Missing class kotlinx.serialization.KSerializer", source: "gradle" },
  { path: "app/build.gradle.kts", line: 22, column: 13, severity: "warning", message: "isMinifyEnabled without shrinkResources", source: "lint" },
  { path: "app/src/main/java/com/trailhead/app/ui/TrailListScreen.kt", line: 25, column: 25, severity: "info", message: "String concatenation in Text; consider a string resource", source: "lint" },
];

const gitLog: GitCommit[] = [
  { sha: "f04e9a2", message: "Add serialization keep rules", author: "AppPilot agent", authoredAt: ago(6), filesChanged: 1, aiTaskId: "t_2" },
  { sha: "c9d1e07", message: "Add keep rule for data package", author: "AppPilot agent", authoredAt: ago(14), filesChanged: 1, aiTaskId: "t_2" },
  { sha: "a1b2c3d", message: "Search trails by name in repository", author: "AppPilot agent", authoredAt: ago(60 * 3), filesChanged: 1, aiTaskId: "t_0" },
  { sha: "7e6d5c4", message: "Bump compileSdk to 35", author: "Mira Kapoor", authoredAt: ago(60 * 24 * 2), filesChanged: 1, aiTaskId: null },
  { sha: "0a9b8c7", message: "Initial project generated", author: "AppPilot agent", authoredAt: ago(60 * 24 * 12), filesChanged: 19, aiTaskId: null },
];

const adminUsers: AdminUser[] = [
  { ...user, planId: "pro", status: "active", projectCount: 4, lastActiveAt: ago(1) },
  { id: "u_2", name: "Arjun Mehta", email: "arjun@example.dev", avatarUrl: null, role: "user", emailVerified: true, createdAt: ago(60 * 24 * 40), planId: "team", status: "active", projectCount: 11, lastActiveAt: ago(30) },
  { id: "u_3", name: "Lena Fischer", email: "lena@example.dev", avatarUrl: null, role: "user", emailVerified: false, createdAt: ago(60 * 24 * 2), planId: "free", status: "active", projectCount: 1, lastActiveAt: ago(60 * 20) },
  { id: "u_4", name: "Tomás Rivera", email: "tomas@example.dev", avatarUrl: null, role: "user", emailVerified: true, createdAt: ago(60 * 24 * 120), planId: "free", status: "suspended", projectCount: 2, lastActiveAt: ago(60 * 24 * 14) },
];

const workers: WorkerStatus[] = [
  { id: "build-1", pool: "build", state: "busy", currentJobId: "b_14", lastHeartbeatAt: ago(0) },
  { id: "build-2", pool: "build", state: "idle", currentJobId: null, lastHeartbeatAt: ago(0) },
  { id: "agent-1", pool: "agent", state: "busy", currentJobId: "t_2", lastHeartbeatAt: ago(0) },
  { id: "agent-2", pool: "agent", state: "busy", currentJobId: "t_3", lastHeartbeatAt: ago(0) },
  { id: "emu-1", pool: "emulator", state: "draining", currentJobId: null, lastHeartbeatAt: ago(1) },
  { id: "emu-2", pool: "emulator", state: "offline", currentJobId: null, lastHeartbeatAt: ago(48) },
];

const audit: AdminAuditEvent[] = [
  { id: "au1", actorEmail: "mira@example.dev", action: "user.suspend", target: "tomas@example.dev", at: ago(60 * 24 * 13) },
  { id: "au2", actorEmail: "mira@example.dev", action: "plan.update", target: "pro", at: ago(60 * 24 * 20) },
];

const envVars: Record<string, ProjectEnvVar[]> = {
  p_trailhead: [
    { key: "MAPS_API_KEY", value: null, secret: true },
    { key: "BUILD_FLAVOR", value: "playstore", secret: false },
  ],
};

export const db = {
  signedIn: !!activeDemoSession,
  user: activeDemoSession ? toSessionUser(activeDemoSession.user) : user,
  prefs: {
    theme: "light",
    defaultLanguage: "kotlin",
    defaultUiToolkit: "compose",
    emailNotifications: { buildFailed: true, agentTaskCompleted: true, usageThreshold: false },
  } as UserPreferences,
  projects,
  files: new Map<string, Map<string, MockFile>>([
    ["p_trailhead", trailFiles],
    [
      "p_ledgerly",
      filesFrom({
        "settings.gradle": "include ':app'\n",
        "app/build.gradle": "apply plugin: 'com.android.application'\n\nandroid {\n    namespace 'io.ledgerly'\n    compileSdk 34\n}\n",
        "app/src/main/java/io/ledgerly/MainActivity.java": "package io.ledgerly;\n\nimport android.app.Activity;\nimport android.os.Bundle;\n\npublic class MainActivity extends Activity {\n    @Override\n    protected void onCreate(Bundle savedInstanceState) {\n        super.onCreate(savedInstanceState);\n        setContentView(R.layout.activity_main);\n    }\n}\n",
        "app/src/main/res/layout/activity_main.xml": "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n<LinearLayout xmlns:android=\"http://schemas.android.com/apk/res/android\"\n    android:layout_width=\"match_parent\"\n    android:layout_height=\"match_parent\"\n    android:orientation=\"vertical\" />\n",
      }),
    ],
    [
      "p_weather",
      filesFrom({
        "ANALYSIS.md": "# Decompiled APK\n\nThese files were reconstructed from weatherpro-2.4.1.apk with a decompiler.\nThey are **not** the original source: names may be obfuscated and code may not compile.\n",
        "decompiled/AndroidManifest.xml": "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n<manifest package=\"com.example.weatherpro\" />\n",
        "decompiled/sources/com/example/weatherpro/a/b.java": "package com.example.weatherpro.a;\n\n/* Decompiled — obfuscated class */\npublic final class b {\n    public static String a(double d) {\n        return String.valueOf(Math.round(d)) + \"°\";\n    }\n}\n",
      }),
    ],
    ["p_pantry", new Map()],
  ]),
  tasks,
  timelines,
  changeSets,
  messages,
  builds,
  buildLogs: new Map<string, string[]>(),
  artifacts,
  testJobs,
  testCases,
  screenshots,
  plans,
  subscription,
  invoices,
  activity,
  diagnostics,
  gitLog,
  adminUsers,
  workers,
  audit,
  envVars,
  uploads: new Map<string, UploadSession>(),
};
