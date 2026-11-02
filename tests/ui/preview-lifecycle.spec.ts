import {test,expect} from '@playwright/test';
import path from 'node:path';

test('选区刷新时保留当前图片地址，替换后再释放旧图片',async({page})=>{
 await page.goto('/');await page.getByRole('button',{name:'导入 NEF 照片'}).click();
 await page.getByLabel('NEF 文件').setInputFiles(path.resolve('DSC_0002.NEF'));
 await page.getByRole('button',{name:'导入并分析原片'}).click();
 await expect(page.getByRole('button',{name:'关闭导入'})).toHaveCount(0);
 await expect(page.getByAltText('原始解码预览')).toBeVisible({timeout:40000});
 await page.getByRole('button',{name:'识别本地选区'}).click();
 await expect(page.locator('.region-tabs')).toContainText('人物',{timeout:30000});
 const after=page.getByAltText('调整后近似预览'),original=page.getByAltText('原始解码预览');
 await expect.poll(async()=>await after.getAttribute('src')!==await original.getAttribute('src')).toBe(true);
 await expect(page.getByText('正在更新预览…')).toHaveCount(0);
 const previous=(await after.getAttribute('src'))!;
 let release!:()=>void;const gate=new Promise<void>(resolve=>release=resolve);let pending=0;
 await page.route('**/api/jobs/*/preview',async route=>{pending++;await gate;try{await route.continue();}catch{/* canceled by a newer render */}});
 try{
   const saved=page.waitForResponse(r=>r.request().method()==='PUT'&&r.url().includes('/regions/'));
   await page.getByLabel('选区边缘柔化').fill('2');expect((await saved).ok()).toBeTruthy();
   await expect.poll(()=>pending).toBeGreaterThan(0);
   expect(await after.getAttribute('src')).toBe(previous);
   const live=await page.evaluate(async src=>{try{return (await fetch(src)).ok;}catch{return false;}},previous);
   expect(live,'刷新期间仍在展示的图片必须保持可读取').toBe(true);
   await expect(page.getByRole('alert')).toHaveCount(0);
   release();
   await expect.poll(async()=>await after.getAttribute('src')).not.toBe(previous);
   await expect.poll(()=>page.evaluate(async src=>{try{return (await fetch(src)).ok;}catch{return false;}},previous)).toBe(false);
 }finally{release();await page.unrouteAll({behavior:'wait'});}
 const canvas=page.getByLabel('局部选区编辑画布');
 await expect(canvas).toHaveAttribute('aria-busy','false');
 let firstMask=true;
 await page.route('**/api/jobs/*/regions/*/mask',async route=>{if(firstMask){firstMask=false;await route.fulfill({status:200,contentType:'image/png',body:'invalid-png'});}else await route.continue();});
 await page.getByRole('checkbox',{name:'显示选区',exact:true}).uncheck();
 await expect(canvas).toHaveAttribute('aria-busy','false');
 await page.getByRole('checkbox',{name:'显示选区',exact:true}).check();
 await expect(page.getByRole('alert')).toContainText('选区图像解码失败');
 await page.getByRole('button',{name:'重试选区预览',exact:true}).click();
 await expect(canvas).toHaveAttribute('aria-busy','false');
 await expect(page.getByRole('alert')).toHaveCount(0);
 await page.unrouteAll({behavior:'wait'});
});
