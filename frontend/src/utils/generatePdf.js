import jsPDF from 'jspdf';
import autoTable from 'jspdf-autotable';

/**
 * Helper function to safely parse stringified JSON content if necessary.
 * @param {any} val - Content data or JSON string
 * @returns {any} Parsed content object or original value
 */
function safeParse(val) {
  if (typeof val !== 'string') return val;
  try {
    return JSON.parse(val);
  } catch {
    return val;
  }
}

/**
 * Adds a section heading to the PDF document.
 * @param {jsPDF} doc - jsPDF document instance
 * @param {string} title - Section heading text
 * @param {number} yPos - Current vertical Y position
 * @returns {number} Updated vertical Y position
 */
function addSection(doc, title, yPos) {
  if (yPos + 14 > 280) {
    doc.addPage();
    yPos = 20;
  }
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(14);
  doc.setTextColor(30, 41, 59); // Dark color (slate-800)
  doc.text(title, 15, yPos);
  return yPos + 7;
}

/**
 * Renders wrapped text with automatic page overflow handling.
 * @param {jsPDF} doc - jsPDF instance
 * @param {string} text - Text to print
 * @param {number} yPos - Current vertical Y position
 * @param {object} options - Font and styling options
 * @returns {number} Updated vertical Y position
 */
function renderWrappedText(doc, text, yPos, options = {}) {
  if (!text) return yPos;
  const str = typeof text === 'string' ? text : String(text);
  const fontSize = options.fontSize || 10;
  const fontStyle = options.fontStyle || 'normal';
  const textColor = options.textColor || [51, 65, 85];
  const lineHeight = options.lineHeight || 5;

  doc.setFont('helvetica', fontStyle);
  doc.setFontSize(fontSize);
  doc.setTextColor(textColor[0], textColor[1], textColor[2]);

  const lines = doc.splitTextToSize(str, 180);
  let curY = yPos;
  for (const line of lines) {
    if (curY + lineHeight > 280) {
      doc.addPage();
      curY = 20;
    }
    doc.text(line, 15, curY);
    curY += lineHeight;
  }
  return curY + 4;
}

/**
 * Renders monospace text (e.g. SQL, PL/SQL, JSON) with page overflow handling.
 * @param {jsPDF} doc - jsPDF instance
 * @param {string|object} text - Code or text content
 * @param {number} yPos - Current vertical Y position
 * @returns {number} Updated vertical Y position
 */
function renderMonospace(doc, text, yPos) {
  if (!text) return yPos;
  const str = typeof text === 'string' ? text : JSON.stringify(text, null, 2);
  doc.setFont('courier', 'normal');
  doc.setFontSize(8);
  doc.setTextColor(51, 65, 85);

  const lines = doc.splitTextToSize(str, 180);
  const lineHeight = 3.8;
  let curY = yPos;
  for (const line of lines) {
    if (curY + lineHeight > 280) {
      doc.addPage();
      curY = 20;
    }
    doc.text(line, 15, curY);
    curY += lineHeight;
  }
  return curY + 6;
}

/**
 * Renders an autoTable using HighRadius styling.
 * @param {jsPDF} doc - jsPDF instance
 * @param {Array<string[]>} head - Table header columns
 * @param {Array<any[]>} body - Table rows
 * @param {number} startY - Start vertical position
 * @returns {number} Updated vertical position after table
 */
function renderTable(doc, head, body, startY) {
  let y = startY;
  if (y + 20 > 280) {
    doc.addPage();
    y = 20;
  }

  autoTable(doc, {
    startY: y,
    head,
    body,
    theme: 'grid',
    headStyles: { fillColor: [0, 150, 230] }, // HighRadius blue (#0096e6)
    styles: { fontSize: 9 },
    margin: { left: 15, right: 15 },
  });

  return doc.lastAutoTable ? doc.lastAutoTable.finalY + 8 : y + 20;
}

/**
 * Generates a PDF from artifact data and opens it in a new browser tab.
 * @param {object} artifact - Artifact metadata (must have artifact_type)
 * @param {object} version - Version object (must have content and version_number)
 */
export function openArtifactAsPdf(artifact, version) {
  // 1. Create a new jsPDF instance (portrait, A4)
  const doc = new jsPDF({
    orientation: 'portrait',
    unit: 'mm',
    format: 'a4',
  });

  // 2. Extract content and artifactType
  const content = safeParse(version?.content) || {};
  const artifactType = artifact?.artifact_type || '';

  let y = 20;

  // 3. Add a title header
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(20);
  doc.setTextColor(30, 41, 59);

  const titleText = content.document_title || (artifactType ? artifactType.replace(/_/g, ' ') : 'Artifact Document');
  const titleLines = doc.splitTextToSize(titleText, 180);
  for (const line of titleLines) {
    if (y + 9 > 280) {
      doc.addPage();
      y = 20;
    }
    doc.text(line, 15, y);
    y += 8;
  }

  // Metadata line below title
  doc.setFont('helvetica', 'normal');
  doc.setFontSize(10);
  doc.setTextColor(100, 116, 139);
  const versionNum = version?.version_number !== undefined ? version.version_number : 1;
  const metaLine = `Stage: ${artifactType} | Version: v${versionNum} | Generated: ${new Date().toLocaleDateString()}`;
  if (y + 6 > 280) {
    doc.addPage();
    y = 20;
  }
  doc.text(metaLine, 15, y);
  y += 6;

  // Horizontal line separator
  doc.setDrawColor(226, 232, 240);
  doc.setLineWidth(0.5);
  doc.line(15, y, 195, y);
  y += 10;

  // 4. Render sections based on artifact type
  switch (artifactType) {
    case 'CONTEXT_ANALYSIS': {
      let renderedAny = false;

      // Section 'Business Objective'
      if (content.business_objective) {
        y = addSection(doc, 'Business Objective', y);
        y = renderWrappedText(doc, content.business_objective, y);
        renderedAny = true;
      }

      // Section 'Identified Entities'
      if (Array.isArray(content.identified_entities) && content.identified_entities.length > 0) {
        y = addSection(doc, 'Identified Entities', y);
        const head = [['Entity', 'ERP Table', 'Role']];
        const body = content.identified_entities.map((e) => [
          e.business_name || '',
          e.erp_table || '',
          e.role || '',
        ]);
        y = renderTable(doc, head, body, y);
        renderedAny = true;
      }

      // Section 'Relationships'
      if (Array.isArray(content.relationships) && content.relationships.length > 0) {
        y = addSection(doc, 'Relationships', y);
        content.relationships.forEach((rel) => {
          const joinType = rel.join_type ? ` (${rel.join_type})` : '';
          const header = `${rel.from_entity || ''} → ${rel.to_entity || ''}${joinType}`;
          y = renderWrappedText(doc, header, y, { fontSize: 10, fontStyle: 'bold', lineHeight: 5 });
          if (rel.join_condition) {
            y = renderWrappedText(doc, `ON ${rel.join_condition}`, y, {
              fontSize: 9,
              fontStyle: 'normal',
              textColor: [71, 85, 105],
              lineHeight: 4.5,
            });
          }
          y += 2;
        });
        renderedAny = true;
      }

      if (!renderedAny) {
        y = addSection(doc, 'Content', y);
        y = renderMonospace(doc, content, y);
      }
      break;
    }

    case 'FDD': {
      // Section 'Attribute Mappings'
      if (Array.isArray(content.attribute_mappings) && content.attribute_mappings.length > 0) {
        y = addSection(doc, 'Attribute Mappings', y);
        const head = [['Seq', 'Attribute', 'Source Table', 'Column', 'Data Type', 'Transformation']];
        const body = content.attribute_mappings.map((m, idx) => [
          m.seq !== undefined ? m.seq : idx + 1,
          m.business_attribute || '',
          m.source_table || '',
          m.source_column || '',
          m.data_type || '',
          m.transformation || 'Direct',
        ]);
        y = renderTable(doc, head, body, y);
      } else {
        y = addSection(doc, 'Content', y);
        y = renderMonospace(doc, content, y);
      }
      break;
    }

    case 'TDD': {
      let renderedAny = false;

      // Section 'Technical Architecture'
      if (content.technical_architecture) {
        y = addSection(doc, 'Technical Architecture', y);
        const ta = content.technical_architecture;
        let lines = [];
        if (typeof ta === 'object' && ta !== null) {
          if (ta.package_name) lines.push(`Package Name: ${ta.package_name}`);
          if (ta.schema_owner) lines.push(`Schema Owner: ${ta.schema_owner}`);
          Object.entries(ta).forEach(([k, v]) => {
            if (k !== 'package_name' && k !== 'schema_owner' && typeof v !== 'object') {
              const label = k.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
              lines.push(`${label}: ${v}`);
            }
          });
        } else {
          lines.push(String(ta));
        }
        y = renderWrappedText(doc, lines.join('\n'), y);
        renderedAny = true;
      }

      // Section 'Watermark Strategy'
      if (content.watermark_strategy) {
        y = addSection(doc, 'Watermark Strategy', y);
        const ws = content.watermark_strategy;
        let lines = [];
        if (typeof ws === 'object' && ws !== null) {
          if (ws.tracking_table) lines.push(`Tracking Table: ${ws.tracking_table}`);
          if (ws.watermark_column) lines.push(`Watermark Column: ${ws.watermark_column}`);
          Object.entries(ws).forEach(([k, v]) => {
            if (k !== 'tracking_table' && k !== 'watermark_column' && typeof v !== 'object') {
              const label = k.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
              lines.push(`${label}: ${v}`);
            }
          });
        } else {
          lines.push(String(ws));
        }
        y = renderWrappedText(doc, lines.join('\n'), y);
        renderedAny = true;
      }

      if (!renderedAny) {
        y = addSection(doc, 'Content', y);
        y = renderMonospace(doc, content, y);
      }
      break;
    }

    case 'SQL': {
      // Section 'Extraction SQL'
      if (content.extraction_sql) {
        y = addSection(doc, 'Extraction SQL', y);
        y = renderMonospace(doc, content.extraction_sql, y);
      } else {
        y = addSection(doc, 'Content', y);
        y = renderMonospace(doc, content, y);
      }
      break;
    }

    case 'PKS':
    case 'PKB': {
      let renderedAny = false;

      // Section 'Package Specification'
      if (content.pks_content) {
        y = addSection(doc, 'Package Specification', y);
        y = renderMonospace(doc, content.pks_content, y);
        renderedAny = true;
      }

      // Section 'Package Body'
      if (content.pkb_content) {
        y = addSection(doc, 'Package Body', y);
        y = renderMonospace(doc, content.pkb_content, y);
        renderedAny = true;
      }

      if (!renderedAny) {
        y = addSection(doc, 'Content', y);
        y = renderMonospace(doc, content, y);
      }
      break;
    }

    case 'DEPLOYMENT': {
      // Section 'Installation Steps'
      if (Array.isArray(content.installation_steps) && content.installation_steps.length > 0) {
        y = addSection(doc, 'Installation Steps', y);
        const head = [['Step', 'Name', 'File', 'Command']];
        const body = content.installation_steps.map((s, idx) => [
          s.step_number !== undefined ? s.step_number : idx + 1,
          s.name || '',
          s.file_or_action || '',
          s.command || '',
        ]);
        y = renderTable(doc, head, body, y);
      } else {
        y = addSection(doc, 'Content', y);
        y = renderMonospace(doc, content, y);
      }
      break;
    }

    default: {
      // Fallback for any other artifact type
      y = addSection(doc, 'Content', y);
      y = renderMonospace(doc, JSON.stringify(content, null, 2), y);
      break;
    }
  }

  // 8. Output as blob and open in new tab
  const pdfBlob = doc.output('blob');
  const url = URL.createObjectURL(pdfBlob);
  window.open(url, '_blank');
}
