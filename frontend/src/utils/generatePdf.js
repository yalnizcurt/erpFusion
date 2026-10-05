import { label } from './product';

function parseContent(value) {
  if (typeof value !== 'string') return value ?? {};
  try { return JSON.parse(value); } catch { return value; }
}

function addHeading(doc, text, y, level) {
  if (y + 12 > 280) { doc.addPage(); y = 20; }
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(level ? 11 : 14);
  doc.setTextColor(30, 41, 59);
  doc.text(text, 15, y);
  return y + (level ? 6 : 8);
}

function addText(doc, value, y) {
  doc.setFont('helvetica', 'normal');
  doc.setFontSize(10);
  doc.setTextColor(51, 65, 85);
  for (const line of doc.splitTextToSize(value, 180)) {
    if (y + 5 > 280) { doc.addPage(); y = 20; }
    doc.text(line, 15, y);
    y += 5;
  }
  return y + 4;
}

function renderValue(doc, title, value, y, level = 0) {
  y = addHeading(doc, title, y, level);
  if (Array.isArray(value)) {
    if (!value.length) return addText(doc, '(empty)', y);
    value.forEach((item, index) => {
      y = item && typeof item === 'object'
        ? renderValue(doc, `${title} ${index + 1}`, item, y, level + 1)
        : addText(doc, `• ${item == null ? String(item) : String(item) || '(empty)'}`, y);
    });
  } else if (value && typeof value === 'object') {
    const entries = Object.entries(value);
    if (!entries.length) return addText(doc, '(empty)', y);
    entries.forEach(([key, item]) => { y = renderValue(doc, label(key), item, y, level + 1); });
  } else {
    y = addText(doc, value == null ? String(value) : String(value) || '(empty)', y);
  }
  return y;
}

export async function createArtifactPdf(artifact, version) {
  const { default: jsPDF } = await import('jspdf');
  const doc = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' });
  const content = parseContent(version?.content);
  const artifactType = artifact?.artifact_type || 'Artifact';
  const title = content?.document_title || label(artifactType);
  let y = addHeading(doc, title, 20, 0);

  doc.setFont('helvetica', 'normal');
  doc.setFontSize(9);
  doc.setTextColor(100, 116, 139);
  const metadata = `Stage: ${label(artifactType)} | Version: v${version?.version_number ?? 'Unknown'} | State: ${version?.state || 'Unknown'} | Generated: ${version?.generated_at || 'Unavailable'}`;
  for (const line of doc.splitTextToSize(metadata, 180)) {
    if (y + 5 > 280) { doc.addPage(); y = 20; }
    doc.text(line, 15, y);
    y += 5;
  }
  doc.setDrawColor(226, 232, 240);
  doc.setLineWidth(0.5);
  doc.line(15, y + 2, 195, y + 2);
  y += 10;

  if (content && typeof content === 'object' && !Array.isArray(content)) {
    Object.entries(content).forEach(([key, value]) => { y = renderValue(doc, label(key), value, y); });
    if (!Object.keys(content).length) y = addText(doc, '(empty)', y);
  } else {
    y = renderValue(doc, 'Content', content, y);
  }
  return doc.output('blob');
}
