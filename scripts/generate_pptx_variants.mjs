import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

const artifactTool = process.env.SUNIC_ARTIFACT_TOOL_MODULE
  ? await import(pathToFileURL(process.env.SUNIC_ARTIFACT_TOOL_MODULE).href)
  : await import("@oai/artifact-tool");
const { FileBlob, PresentationFile } = artifactTool;

const variants = [
  {
    file: "01_bad_bullet_spacing.pptx",
    label: "불릿·공백 오류",
    expected: ["bullet", "cleanup"],
    mutate: ({ body, bodyRecord }) => {
      const line = bodyRecord.text
        .split(/\r?\n/)
        .find((item) => item.trim() && item.includes("CEO"));
      if (!line) throw new Error("슬라이드 1 본문에서 CEO 문장을 찾지 못했습니다.");
      body.text.replace(line, `▶  ${line.trim()}   `);
    },
  },
  {
    file: "02_wrong_title_font_size.pptx",
    label: "제목 글꼴·크기 오류",
    expected: ["font", "size"],
    mutate: ({ title }) => setTypefaceAndSize(title, "Times New Roman", 40),
  },
  {
    file: "03_wrong_body_font_size.pptx",
    label: "본문 글꼴·크기 오류",
    expected: ["font", "size"],
    mutate: ({ body }) => setTypefaceAndSize(body, "Times New Roman", 24),
  },
  {
    file: "04_shifted_title_position.pptx",
    label: "제목 위치 오류",
    expected: ["position"],
    knownGap: "현재 validator에는 일반 텍스트 상자의 위치를 검사하는 범주가 없다.",
    mutate: ({ title, titleRecord }) => {
      const [left, top, width, height] = titleRecord.bbox;
      title.position = { left: left + 190, top: top + 90, width, height };
    },
  },
  {
    file: "05_wrong_table_geometry.pptx",
    label: "표 위치·너비 오류",
    expected: ["table"],
    mutate: ({ table, tableRecord }) => {
      const [left, top, width, height] = tableRecord.bbox;
      table.position = {
        left: Math.max(0, left - 90),
        top,
        width: width + 180,
        height,
      };
    },
  },
  {
    file: "06_combined_errors.pptx",
    label: "복합 오류",
    expected: ["bullet", "cleanup", "font", "size", "table"],
    mutate: (targets) => {
      variants[0].mutate(targets);
      variants[2].mutate(targets);
      variants[4].mutate(targets);
    },
  },
];

function readArg(name, fallback) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : fallback;
}

function parseInspect(snapshot) {
  return snapshot.ndjson
    .trim()
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

function findRequired(records, description, predicate) {
  const match = records.find(predicate);
  if (!match) throw new Error(`${description} 개체를 찾지 못했습니다.`);
  return match;
}

function setTypefaceAndSize(target, typeface, fontSizePx) {
  target.text.style = { typeface, fontSize: fontSizePx };
}

async function writeBlob(filePath, blob) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(filePath, new Uint8Array(await blob.arrayBuffer()));
}

async function loadTargets(deck) {
  const snapshot = await deck.inspect({
    kind: "slide,textbox,table,notes",
    maxChars: 50000,
  });
  const records = parseInspect(snapshot);
  const titleRecord = findRequired(
    records,
    "슬라이드 1 제목",
    (item) => item.kind === "textbox" && item.slide === 1 && item.name === "TextBox 11",
  );
  const bodyRecord = findRequired(
    records,
    "슬라이드 1 본문",
    (item) => item.kind === "textbox" && item.slide === 1 && item.placeholder === "body",
  );
  const tableRecord = findRequired(
    records,
    "슬라이드 1 표",
    (item) => item.kind === "table" && item.slide === 1,
  );

  return {
    titleRecord,
    bodyRecord,
    tableRecord,
    title: deck.resolve(titleRecord.id),
    body: deck.resolve(bodyRecord.id),
    table: deck.resolve(tableRecord.id),
  };
}

async function renderDeck(deck, renderRoot, stem) {
  const deckDir = path.join(renderRoot, stem);
  await fs.mkdir(deckDir, { recursive: true });

  for (const [index, slide] of deck.slides.items.entries()) {
    const slideStem = `slide-${String(index + 1).padStart(2, "0")}`;
    await writeBlob(
      path.join(deckDir, `${slideStem}.png`),
      await deck.export({ slide, format: "png", scale: 1 }),
    );
    const layout = await slide.export({ format: "layout" });
    await fs.writeFile(path.join(deckDir, `${slideStem}.layout.json`), await layout.text());
  }

  await writeBlob(
    path.join(deckDir, "montage.webp"),
    await deck.export({ format: "webp", montage: true, scale: 1 }),
  );
}

async function main() {
  const preparedStarterName = "template-starter.pptx";
  const repoRoot = path.resolve(readArg("--repo", process.cwd()));
  const source = path.resolve(
    readArg("--source", path.join(repoRoot, "app", "assets", "보고양식_Sample_4팀.pptx")),
  );
  const outDir = path.resolve(
    readArg("--out", path.join(repoRoot, "testdata", "pptx_variants")),
  );
  const renderRoot = path.resolve(
    readArg("--render-out", path.join(repoRoot, ".tmp", "ppt-variant-renders")),
  );
  const sourceLabel = readArg(
    "--source-label",
    path.relative(repoRoot, source).replaceAll("\\", "/"),
  );

  await fs.mkdir(outDir, { recursive: true });
  await fs.mkdir(renderRoot, { recursive: true });

  const manifest = {
    schemaVersion: 1,
    generatedAt: new Date().toISOString(),
    source: sourceLabel,
    authoringBase: path.basename(source) === preparedStarterName ? preparedStarterName : sourceLabel,
    purpose: "보고서 PPT 자동 검증·수정 회귀 테스트용 의도적 오류 입력",
    variants: [],
  };

  for (const variant of variants) {
    const deck = await PresentationFile.importPptx(await FileBlob.load(source));
    const targets = await loadTargets(deck);
    variant.mutate(targets);
    deck.slides.items[0].speakerNotes.textFrame.setText(
      `[Sources]\n- 기준 양식: ${manifest.source}\n- 테스트 목적: ${variant.label}`,
    );

    const stem = path.basename(variant.file, ".pptx");
    await renderDeck(deck, renderRoot, stem);
    const outputPath = path.join(outDir, variant.file);
    await (await PresentationFile.exportPptx(deck)).save(outputPath);
    await fs.rm(`${outputPath}.inspect.ndjson`, { force: true });

    manifest.variants.push({
      file: variant.file,
      label: variant.label,
      expectedCategories: variant.expected,
      knownGap: variant.knownGap ?? null,
      renderDir: path.relative(repoRoot, path.join(renderRoot, stem)).replaceAll("\\", "/"),
    });
    console.log(`generated ${variant.file}`);
  }

  await fs.writeFile(
    path.join(outDir, "manifest.json"),
    `${JSON.stringify(manifest, null, 2)}\n`,
    "utf8",
  );
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
