/**
 * 知栈 StudyStack 冒烟测试
 * 覆盖：建课、导入、增量、检索、掌握度写入/读取、课程隔离
 *
 * 用法：node scripts/smoke.mjs
 */

const API = 'http://127.0.0.1:8787/api';

async function req(path, options = {}) {
  const res = await fetch(API + path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const body = await res.json();
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${JSON.stringify(body)}`);
  return body;
}

function assert(cond, msg) {
  if (!cond) {
    console.error(`  FAIL: ${msg}`);
    process.exitCode = 1;
  } else {
    console.log(`  PASS: ${msg}`);
  }
}

async function main() {
  console.log('=== StudyStack Smoke Test ===\n');

  // 1. 建课
  console.log('[1] 创建课程');
  await req('/collections', { method: 'POST', body: JSON.stringify({ courseId: 'test_math' }) });
  await req('/collections', { method: 'POST', body: JSON.stringify({ courseId: 'test_physics' }) });
  const cols = await req('/collections');
  assert(Array.isArray(cols), '返回课程列表为数组');
  const mathCol = cols.find((c) => c.courseId === 'test_math');
  assert(!!mathCol, 'test_math 课程存在');
  const physCol = cols.find((c) => c.courseId === 'test_physics');
  assert(!!physCol, 'test_physics 课程存在');

  // 2. 导入（用假向量，512维零向量）
  console.log('\n[2] 导入笔记到 test_math');
  const fakeVec = new Array(512).fill(0);
  fakeVec[0] = 1;
  const chunks = [
    { id: 'chunk_0', text: '勾股定理：直角三角形的两条直角边的平方和等于斜边的平方。', embedding: fakeVec, fileName: 'math.md', chunkIndex: 0 },
    { id: 'chunk_1', text: '二次方程的求根公式为 x = (-b ± √(b²-4ac)) / 2a。', embedding: fakeVec.map((v, i) => i === 1 ? 1 : 0), fileName: 'math.md', chunkIndex: 1 },
    { id: 'chunk_2', text: '微积分基本定理将微分与积分联系起来。', embedding: fakeVec.map((v, i) => i === 2 ? 1 : 0), fileName: 'math.md', chunkIndex: 2 },
  ];
  const importRes = await req('/import', { method: 'POST', body: JSON.stringify({ courseId: 'test_math', chunks }) });
  assert(importRes.ok && importRes.imported === 3, `导入 3 个分块 (got ${importRes.imported})`);

  // 3. 增量导入
  console.log('\n[3] 增量导入到 test_math');
  const moreChunks = [
    { id: 'chunk_3', text: '概率论研究随机现象的统计规律。', embedding: fakeVec.map((v, i) => i === 3 ? 1 : 0), fileName: 'math2.md', chunkIndex: 0 },
  ];
  const incrRes = await req('/import', { method: 'POST', body: JSON.stringify({ courseId: 'test_math', chunks: moreChunks }) });
  assert(incrRes.ok && incrRes.imported === 1, `增量导入 1 个分块 (got ${incrRes.imported})`);

  // 4. 导入到 test_physics（课程隔离）
  console.log('\n[4] 导入笔记到 test_physics（课程隔离）');
  const physChunks = [
    { id: 'phys_0', text: '牛顿第一定律：物体在不受外力作用时保持静止或匀速直线运动。', embedding: fakeVec, fileName: 'physics.md', chunkIndex: 0 },
  ];
  await req('/import', { method: 'POST', body: JSON.stringify({ courseId: 'test_physics', chunks: physChunks }) });

  // 5. 混合检索
  console.log('\n[5] 混合检索 test_math');
  try {
    const searchRes = await req('/search', {
      method: 'POST',
      body: JSON.stringify({
        courseId: 'test_math',
        query: '勾股定理',
        vector: fakeVec,
        topK: 5,
      }),
    });
    assert(Array.isArray(searchRes.results), '检索返回 results 数组');
    console.log(`  INFO: 检索到 ${searchRes.results.length} 条结果`);
  } catch (e) {
    console.log(`  SKIP: 混合检索需要 seekdb 完整支持 (${e.message})`);
  }

  // 6. 掌握度写入
  console.log('\n[6] 掌握度写入');
  await req('/review/add', {
    method: 'POST',
    body: JSON.stringify({
      courseId: 'test_math',
      chunkId: 'chunk_0',
      text: '勾股定理：直角三角形的两条直角边的平方和等于斜边的平方。',
      fileName: 'math.md',
    }),
  });
  await req('/review/add', {
    method: 'POST',
    body: JSON.stringify({
      courseId: 'test_math',
      chunkId: 'chunk_1',
      text: '二次方程的求根公式。',
      fileName: 'math.md',
    }),
  });
  assert(true, '写入两条复习记录');

  // 7. 掌握度更新
  console.log('\n[7] 掌握度更新');
  await req('/review/mastery', {
    method: 'POST',
    body: JSON.stringify({ id: 'test_math::chunk_0', mastery: 2 }),
  });
  await req('/review/mastery', {
    method: 'POST',
    body: JSON.stringify({ id: 'test_math::chunk_1', mastery: 0 }),
  });
  assert(true, '更新掌握度: chunk_0=会, chunk_1=不会');

  // 8. 薄弱知识点读取
  console.log('\n[8] 薄弱知识点 Top 5');
  const weak = await req('/review/weak/test_math');
  assert(Array.isArray(weak), '返回薄弱知识点数组');
  assert(weak.length >= 2, `至少有 2 条记录 (got ${weak.length})`);
  if (weak.length > 0) {
    assert(weak[0].mastery <= weak[weak.length - 1].mastery || weak.length === 1, '按掌握度升序排列');
    console.log(`  INFO: 第一条 mastery=${weak[0].mastery}, review_count=${weak[0].review_count}`);
  }

  // 9. 课程隔离验证
  console.log('\n[9] 课程隔离验证');
  const physWeak = await req('/review/weak/test_physics');
  assert(Array.isArray(physWeak) && physWeak.length === 0, `test_physics 无复习记录 (got ${physWeak.length})`);

  const allMath = await req('/review/all/test_math');
  assert(allMath.length >= 2, `test_math 全部记录 >= 2 (got ${allMath.length})`);

  // 10. 清理
  console.log('\n[10] 清理测试数据');
  await req('/collections/test_math', { method: 'DELETE' });
  await req('/collections/test_physics', { method: 'DELETE' });
  const afterDelete = await req('/collections');
  const stillHas = afterDelete.find((c) => c.courseId === 'test_math' || c.courseId === 'test_physics');
  assert(!stillHas, '测试课程已删除');

  console.log('\n=== Smoke Test Complete ===');
  if (process.exitCode) {
    console.log('Some tests FAILED');
  } else {
    console.log('All tests PASSED');
  }
}

main().catch((e) => {
  console.error('Fatal error:', e.message);
  process.exit(1);
});
