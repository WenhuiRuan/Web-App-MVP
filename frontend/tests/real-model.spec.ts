import { test, expect } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import type { Snapshot } from '../src/transport/types'

const topics = [
  '大学课堂是否应全面禁止学生使用手机，还是按教学场景有条件允许？',
  '一家30人的软件公司是否应试点每周四天、32小时且不降薪的工作制？请比较交付、客户服务和员工负担。',
]
// Disabled in normal suites: real calls require explicit operator intent.
test.skip(!process.env.PANEL_REAL_VALIDATION, 'Explicitly enable real model validation')
test('two real topics update the studio while awaiting independently scheduled model tasks', async ({ page }) => {
  const output='../work/stage6a-real';mkdirSync(output,{recursive:true})
  const errors: string[]=[];page.on('pageerror',error=>errors.push(error.message))
  const reports: unknown[]=[]
  for (const [index,topic] of topics.entries()) {
    const started=Date.now()
    await page.goto('/#/new')
    await expect(page.locator('.mock-badge')).toHaveText('DeepSeek · deepseek-flash（真实服务）')
    await page.getByLabel('讨论话题').fill(topic)
    await page.getByRole('button',{name:'生成嘉宾阵容',exact:true}).click()
    await expect(page.getByRole('status',{name:'嘉宾阵容生成中'})).toBeVisible()
    await expect(page.getByTestId('roster-person')).toHaveCount(5,{timeout:100000})
    await page.screenshot({path:`${output}/topic-${index+1}-roster.png`})
    const id=page.url().split('/discussion/')[1]
    await page.getByRole('button',{name:'确认阵容，进入演播厅'}).click()
    await expect(page.getByRole('heading',{name:'现场 Transcript'})).toBeVisible()
    const observations: {elapsed_ms:number;state:string;message_count:number;insight_version:number;role_states:string[]}[]=[]
    let data: Snapshot | undefined;let savedWaiting=false;let savedLive=false
    for (let attempt=0;attempt<220;attempt++) {
      data=await (await page.request.get(`/api/discussions/${id}`)).json() as Snapshot
      observations.push({elapsed_ms:Date.now()-started,state:data.discussion.state,message_count:data.messages.length,insight_version:data.insights.version,role_states:data.role_states.map(s=>s.state)})
      if (!savedWaiting && data.role_states.some(s=>s.state==='SPEAKING')) { await page.screenshot({path:`${output}/topic-${index+1}-waiting.png`}); savedWaiting=true }
      if (!savedLive && data.discussion.state==='RUNNING' && data.insights.version>0 && data.messages.length>=4) { await page.screenshot({path:`${output}/topic-${index+1}-live.png`});savedLive=true }
      if (['COMPLETED','FAILED','INTERRUPTED'].includes(data.discussion.state)) break
      await page.waitForTimeout(1000)
    }
    writeFileSync(`${output}/topic-${index+1}.json`,JSON.stringify({snapshot:data,observations},null,2))
    expect(data?.discussion.state,JSON.stringify(data?.discussion)).toBe('COMPLETED')
    expect(savedWaiting).toBeTruthy();expect(savedLive).toBeTruthy()
    await expect(page.getByTestId('message')).toHaveCount(data!.messages.length)
    const ids=await page.getByTestId('message').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('data-message-id')))
    expect(ids).toEqual(data!.messages.map(m=>m.id))
    await page.getByRole('button',{name:'查看主持人总结'}).click()
    await expect(page.getByRole('dialog')).toContainText(data!.summary!.content.split('\n')[0])
    expect(await page.getByRole('dialog').innerText()).not.toContain('{"')
    await page.screenshot({path:`${output}/topic-${index+1}-summary.png`})
    reports.push({discussion_id:id,elapsed_ms:Date.now()-started,message_count:data!.messages.length,insight_version:data!.insights.version})
    await page.getByRole('button',{name:'关闭总结'}).click()
  }
  writeFileSync(`${output}/browser-summary.json`,JSON.stringify({reports,errors},null,2))
  expect(errors).toEqual([])
})
