export interface Chunk {
  index: number;
  text: string;
  start: number;
  end: number;
}

export interface ChunkOptions {
  maxChars: number;
  overlap: number;
}

const SENTENCE_END = /[。！？!?；;\n]/;

/** Split on sentence boundaries, then pack sentences into overlapping windows. */
export function chunkText(input: string, options: ChunkOptions): Chunk[] {
  const text = input.replace(/\r\n/g, '\n').replace(/[ \t]+/g, ' ').trim();
  if (!text) return [];
  const { maxChars, overlap } = options;

  const sentences: { text: string; start: number; end: number }[] = [];
  let cursor = 0;
  let buffer = '';
  let bufferStart = 0;

  for (let i = 0; i < text.length; i++) {
    buffer += text[i];
    if (SENTENCE_END.test(text[i]) || i - bufferStart >= maxChars) {
      const trimmed = buffer.trim();
      if (trimmed) {
        sentences.push({ text: trimmed, start: bufferStart, end: i + 1 });
      }
      buffer = '';
      bufferStart = i + 1;
    }
  }
  const tail = buffer.trim();
  if (tail) sentences.push({ text: tail, start: bufferStart, end: text.length });

  const chunks: Chunk[] = [];
  let current: { text: string; start: number; end: number }[] = [];
  let length = 0;

  const flush = () => {
    if (!current.length) return;
    const body = current.map((s) => s.text).join('').trim();
    chunks.push({
      index: chunks.length,
      text: body,
      start: current[0].start,
      end: current[current.length - 1].end,
    });
    if (overlap > 0) {
      const kept: typeof current = [];
      let keptLength = 0;
      for (let i = current.length - 1; i >= 0; i--) {
        const size = current[i].text.length;
        if (keptLength + size > overlap && kept.length) break;
        kept.unshift(current[i]);
        keptLength += size;
      }
      current = kept;
      length = keptLength;
    } else {
      current = [];
      length = 0;
    }
  };

  for (const sentence of sentences) {
    if (length + sentence.text.length > maxChars && current.length) flush();
    if (sentence.text.length > maxChars) {
      for (let i = 0; i < sentence.text.length; i += maxChars - overlap) {
        chunks.push({
          index: chunks.length,
          text: sentence.text.slice(i, i + maxChars),
          start: sentence.start + i,
          end: sentence.start + Math.min(i + maxChars, sentence.text.length),
        });
      }
      current = [];
      length = 0;
      continue;
    }
    current.push(sentence);
    length += sentence.text.length;
  }
  flush();
  return chunks.filter((c) => c.text.length > 0);
}
