const AUTO_BID_LOG_SHEET_NAME = '자동입찰_변경로그';
const AUTO_BID_SNAPSHOT_SHEET_NAME = '_자동입찰_목표순위_snapshot';
const AUTO_BID_HEADER_ROW = 1;
const AUTO_BID_TARGET_HEADERS = ['목표 순위', '목표순위'];
const AUTO_BID_EXCLUDED_EDITORS = ['API', 'system', '시스템', '자동', 'bot'];
const AUTO_BID_CONTEXT_HEADERS = [
  '키워드',
  '캠페인명',
  '캠페인 ID',
  '광고그룹명',
  '광고그룹 ID',
  '키워드 ID',
  '디바이스',
];
const AUTO_BID_LOG_HEADERS = [
  '변경일시',
  '변경일자',
  '변경자',
  '시트명',
  '행번호',
  '키워드',
  '캠페인명',
  '캠페인 ID',
  '광고그룹명',
  '광고그룹 ID',
  '키워드 ID',
  '디바이스',
  '변경필드',
  '이전값',
  '변경값',
  'raw_text',
];
const AUTO_BID_SNAPSHOT_HEADERS = [
  'key',
  'sheetId',
  'sheetName',
  'rowNumber',
  'keywordId',
  'targetRank',
  'updatedAt',
];

function onEdit(e) {
  if (!e || !e.range || !e.source) return;

  const range = e.range;
  const sheet = range.getSheet();
  const sheetName = sheet.getName();
  if (sheetName === AUTO_BID_LOG_SHEET_NAME || sheetName === AUTO_BID_SNAPSHOT_SHEET_NAME) return;

  const headerMap = getAutoBidHeaderMap_(sheet);
  const targetCol = findAutoBidTargetColumn_(headerMap);
  if (!targetCol || !rangeIntersectsColumn_(range, targetCol)) return;

  const editor = getAutoBidEditor_(e);
  if (isAutoBidExcludedEditor_(editor)) return;

  const firstRow = Math.max(range.getRow(), AUTO_BID_HEADER_ROW + 1);
  const lastRow = range.getLastRow();
  if (firstRow > lastRow) return;

  const logSheet = ensureAutoBidLogSheet_(e.source);
  const snapshotSheet = ensureAutoBidSnapshotSheet_(e.source);
  const snapshotMap = readAutoBidSnapshotMap_(snapshotSheet);
  const now = new Date();
  const changedAt = formatAutoBidDateTime_(now);
  const changedDate = formatAutoBidDate_(now);
  const logs = [];

  for (let rowNumber = firstRow; rowNumber <= lastRow; rowNumber += 1) {
    const rowValues = sheet.getRange(rowNumber, 1, 1, sheet.getLastColumn()).getDisplayValues()[0];
    const newValue = cleanAutoBidRank_(rowValues[targetCol - 1]);
    if (!newValue) continue;

    const context = getAutoBidContext_(rowValues, headerMap);
    const key = autoBidSnapshotKey_(sheet, rowNumber, context['키워드 ID']);
    const oldValue = cleanAutoBidRank_(singleCellOldValue_(e, rowNumber, targetCol) || snapshotMap[key] || '');
    if (oldValue === newValue) continue;

    const keyword = context['키워드'];
    if (!keyword) continue;

    const rawText = buildAutoBidRawText_(keyword, oldValue, newValue);
    logs.push([
      changedAt,
      changedDate,
      editor,
      sheetName,
      rowNumber,
      keyword,
      context['캠페인명'],
      context['캠페인 ID'],
      context['광고그룹명'],
      context['광고그룹 ID'],
      context['키워드 ID'],
      context['디바이스'],
      '목표순위',
      oldValue,
      newValue,
      rawText,
    ]);
    snapshotMap[key] = newValue;
  }

  if (logs.length) {
    logSheet.getRange(logSheet.getLastRow() + 1, 1, logs.length, AUTO_BID_LOG_HEADERS.length).setValues(logs);
  }
  updateAutoBidSnapshotRows_(snapshotSheet, sheet, firstRow, lastRow, targetCol, headerMap);
}

function initializeAutoBidTargetRankSnapshot() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const snapshotSheet = ensureAutoBidSnapshotSheet_(spreadsheet);
  const rows = [AUTO_BID_SNAPSHOT_HEADERS];
  const updatedAt = formatAutoBidDateTime_(new Date());

  spreadsheet.getSheets().forEach((sheet) => {
    const sheetName = sheet.getName();
    if (sheetName === AUTO_BID_LOG_SHEET_NAME || sheetName === AUTO_BID_SNAPSHOT_SHEET_NAME) return;
    const headerMap = getAutoBidHeaderMap_(sheet);
    const targetCol = findAutoBidTargetColumn_(headerMap);
    if (!targetCol) return;

    const lastRow = sheet.getLastRow();
    if (lastRow <= AUTO_BID_HEADER_ROW) return;
    const values = sheet.getRange(AUTO_BID_HEADER_ROW + 1, 1, lastRow - AUTO_BID_HEADER_ROW, sheet.getLastColumn()).getDisplayValues();
    values.forEach((rowValues, offset) => {
      const rowNumber = AUTO_BID_HEADER_ROW + 1 + offset;
      const context = getAutoBidContext_(rowValues, headerMap);
      const targetRank = cleanAutoBidRank_(rowValues[targetCol - 1]);
      const key = autoBidSnapshotKey_(sheet, rowNumber, context['키워드 ID']);
      rows.push([key, sheet.getSheetId(), sheetName, rowNumber, context['키워드 ID'], targetRank, updatedAt]);
    });
  });

  snapshotSheet.clear();
  snapshotSheet.getRange(1, 1, rows.length, AUTO_BID_SNAPSHOT_HEADERS.length).setValues(rows);
  snapshotSheet.hideSheet();
}

function ensureAutoBidLogSheet_(spreadsheet) {
  let sheet = spreadsheet.getSheetByName(AUTO_BID_LOG_SHEET_NAME);
  if (!sheet) sheet = spreadsheet.insertSheet(AUTO_BID_LOG_SHEET_NAME);
  const header = sheet.getRange(1, 1, 1, AUTO_BID_LOG_HEADERS.length).getDisplayValues()[0];
  if (header.join('') !== AUTO_BID_LOG_HEADERS.join('')) {
    sheet.getRange(1, 1, 1, AUTO_BID_LOG_HEADERS.length).setValues([AUTO_BID_LOG_HEADERS]);
  }
  return sheet;
}

function ensureAutoBidSnapshotSheet_(spreadsheet) {
  let sheet = spreadsheet.getSheetByName(AUTO_BID_SNAPSHOT_SHEET_NAME);
  if (!sheet) sheet = spreadsheet.insertSheet(AUTO_BID_SNAPSHOT_SHEET_NAME);
  const header = sheet.getRange(1, 1, 1, AUTO_BID_SNAPSHOT_HEADERS.length).getDisplayValues()[0];
  if (header.join('') !== AUTO_BID_SNAPSHOT_HEADERS.join('')) {
    sheet.getRange(1, 1, 1, AUTO_BID_SNAPSHOT_HEADERS.length).setValues([AUTO_BID_SNAPSHOT_HEADERS]);
  }
  sheet.hideSheet();
  return sheet;
}

function updateAutoBidSnapshotRows_(snapshotSheet, sheet, firstRow, lastRow, targetCol, headerMap) {
  const existingValues = snapshotSheet.getDataRange().getDisplayValues();
  const rowsByKey = {};
  existingValues.slice(1).forEach((row, offset) => {
    if (row[0]) rowsByKey[row[0]] = offset + 2;
  });

  const updatedAt = formatAutoBidDateTime_(new Date());
  const upserts = [];
  for (let rowNumber = firstRow; rowNumber <= lastRow; rowNumber += 1) {
    const rowValues = sheet.getRange(rowNumber, 1, 1, sheet.getLastColumn()).getDisplayValues()[0];
    const context = getAutoBidContext_(rowValues, headerMap);
    const key = autoBidSnapshotKey_(sheet, rowNumber, context['키워드 ID']);
    const values = [
      key,
      sheet.getSheetId(),
      sheet.getName(),
      rowNumber,
      context['키워드 ID'],
      cleanAutoBidRank_(rowValues[targetCol - 1]),
      updatedAt,
    ];
    const existingRow = rowsByKey[key];
    if (existingRow) {
      snapshotSheet.getRange(existingRow, 1, 1, AUTO_BID_SNAPSHOT_HEADERS.length).setValues([values]);
    } else {
      upserts.push(values);
    }
  }
  if (upserts.length) {
    snapshotSheet.getRange(snapshotSheet.getLastRow() + 1, 1, upserts.length, AUTO_BID_SNAPSHOT_HEADERS.length).setValues(upserts);
  }
}

function readAutoBidSnapshotMap_(snapshotSheet) {
  const values = snapshotSheet.getDataRange().getDisplayValues();
  const map = {};
  values.slice(1).forEach((row) => {
    if (row[0]) map[row[0]] = row[5] || '';
  });
  return map;
}

function getAutoBidHeaderMap_(sheet) {
  const headers = sheet.getRange(AUTO_BID_HEADER_ROW, 1, 1, sheet.getLastColumn()).getDisplayValues()[0];
  const map = {};
  headers.forEach((header, index) => {
    const key = normalizeAutoBidHeader_(header);
    if (key) map[key] = index + 1;
  });
  return map;
}

function findAutoBidTargetColumn_(headerMap) {
  for (const header of AUTO_BID_TARGET_HEADERS) {
    const col = headerMap[normalizeAutoBidHeader_(header)];
    if (col) return col;
  }
  return 0;
}

function getAutoBidContext_(rowValues, headerMap) {
  const context = {};
  AUTO_BID_CONTEXT_HEADERS.forEach((header) => {
    const col = headerMap[normalizeAutoBidHeader_(header)];
    context[header] = col ? String(rowValues[col - 1] || '').trim() : '';
  });
  return context;
}

function rangeIntersectsColumn_(range, column) {
  return range.getColumn() <= column && column <= range.getLastColumn();
}

function singleCellOldValue_(e, rowNumber, targetCol) {
  if (e.range.getNumRows() !== 1 || e.range.getNumColumns() !== 1) return '';
  if (e.range.getRow() !== rowNumber || e.range.getColumn() !== targetCol) return '';
  return e.oldValue || '';
}

function autoBidSnapshotKey_(sheet, rowNumber, keywordId) {
  return [sheet.getSheetId(), keywordId || `row:${rowNumber}`].join(':');
}

function getAutoBidEditor_(e) {
  try {
    if (e && e.user) {
      return typeof e.user.getEmail === 'function' ? e.user.getEmail() : String(e.user);
    }
  } catch (error) {
    // fall back to the session user below
  }
  try {
    return Session.getActiveUser().getEmail() || Session.getEffectiveUser().getEmail() || '';
  } catch (error) {
    return '';
  }
}

function isAutoBidExcludedEditor_(editor) {
  const text = String(editor || '').toLowerCase();
  return AUTO_BID_EXCLUDED_EDITORS.some((keyword) => text.includes(keyword.toLowerCase()));
}

function buildAutoBidRawText_(keyword, oldValue, newValue) {
  if (oldValue) return `${keyword} 목표순위 ${rankText_(oldValue)} → ${rankText_(newValue)} 변경`;
  return `${keyword} 목표순위 ${rankText_(newValue)}로 신규 설정`;
}

function rankText_(value) {
  const text = cleanAutoBidRank_(value);
  return text.includes('순위') ? text : `${text}순위`;
}

function cleanAutoBidRank_(value) {
  return String(value || '').trim().replace(/\.0$/, '').replace(/순위/g, '').trim();
}

function normalizeAutoBidHeader_(value) {
  return String(value || '').trim().toLowerCase().replace(/[\s_\-]+/g, '');
}

function formatAutoBidDateTime_(date) {
  return Utilities.formatDate(date, Session.getScriptTimeZone() || 'Asia/Seoul', 'yyyy-MM-dd HH:mm:ss');
}

function formatAutoBidDate_(date) {
  return Utilities.formatDate(date, Session.getScriptTimeZone() || 'Asia/Seoul', 'yyyy-MM-dd');
}
