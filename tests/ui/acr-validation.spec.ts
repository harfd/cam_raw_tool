import {test,expect} from '@playwright/test';
import path from 'node:path';

async function openPhoto(page:any){
 await page.goto('/');await page.getByRole('button',{name:'导入 NEF 照片'}).click();
 await page.getByLabel('NEF 文件').setInputFiles(path.resolve('DSC_0002.NEF'));
 await page.getByRole('button',{name:'导入并分析原片'}).click();
 await expect(page.getByRole('button',{name:'关闭导入'})).toHaveCount(0,{timeout:40000});
 const panel=page.getByRole('region',{name:'ACR 对照验证'});
 await expect(panel.getByRole('heading',{name:'高精度预览与 ACR 对照'})).toBeVisible({timeout:40000});
 return panel;
}

test('未安装 Photoshop 时说明原因、允许重新检测，无手动成片导入',async({page})=>{
 let available=false;
 await page.route('**/api/photoshop',route=>route.fulfill({json:{available,message:available?'已找到 Photoshop':'未找到可用的 Photoshop 接口'}}));
 const panel=await openPhoto(page);
 await expect(panel.getByRole('button',{name:'生成 ACR 实际预览',exact:true})).toBeDisabled();
 expect(await panel.locator('input[type=file]').count()).toBe(0);
 available=true;await panel.getByRole('button',{name:'重新检测 Photoshop'}).click();
 await expect(panel.getByRole('button',{name:'生成 ACR 实际预览',exact:true})).toBeEnabled();
 await page.route('**/validation/render?*',route=>route.fulfill({status:409,json:{detail:'Photoshop 正在生成另一份预览，请等待完成后重试。'}}));
 await panel.getByRole('button',{name:'生成 ACR 实际预览',exact:true}).click();
 await expect(panel.getByRole('alert')).toContainText('Photoshop 正在生成另一份预览');
 await expect(panel.getByRole('button',{name:'生成 ACR 实际预览',exact:true})).toBeEnabled();
});

test('真实 Photoshop 一键渲染、自动对照、重开恢复和方案过期',async({page})=>{
 test.skip(process.env.RAW_STUDIO_TEST_PHOTOSHOP!=='1','Opt in to opening real Photoshop');
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 const panel=await openPhoto(page);
 await expect(panel.getByRole('button',{name:'生成 ACR 实际预览',exact:true})).toBeEnabled();
 const rendering=page.waitForResponse(r=>r.url().includes('/validation/render?')&&r.request().method()==='POST');
 await panel.getByRole('button',{name:'生成 ACR 实际预览',exact:true}).click();
 const response=await rendering;expect(response.status()).toBe(202);const snapshot=await response.json();
 expect(snapshot.photoshop.status).toBe('running');
 await expect(panel.getByRole('button',{name:'Photoshop 正在渲染…'})).toBeDisabled();
 await expect(panel.getByAltText('ACR 实际成片对照')).toBeVisible({timeout:60000});
 await expect(panel.getByAltText('ACR 与本地预览的色差图')).toBeVisible();
 await expect(panel.locator('table tbody tr').first()).toContainText('全图');
 await expect(panel.getByText(/由 Photoshop .* 自动生成/)).toBeVisible();
 expect(await panel.locator('input[type=file]').count()).toBe(0);
 await page.screenshot({path:'work/ui-photoshop-validation.png',fullPage:true});
 const [download]=await Promise.all([page.waitForEvent('download'),panel.getByRole('button',{name:'保存对照报告'}).click()]);
 expect(download.suggestedFilename()).toBe('ACR对照报告.json');
 await page.reload();
 await page.getByRole('heading',{name:'DSC_0002.NEF',exact:true}).waitFor({timeout:20000});
 await expect(panel.getByAltText('ACR 实际成片对照')).toBeVisible();
 await page.locator('#Contrast2012').fill('11');
 await expect(panel.getByRole('status')).toContainText('当前方案或选区已变化');
 await panel.getByText('查看原尺寸局部（100%）',{exact:true}).click();
 await panel.getByRole('button',{name:'查看局部 100%'}).click();
 await expect(panel.getByAltText('原尺寸局部预览')).toBeVisible({timeout:40000});
 expect(await panel.getByAltText('原尺寸局部预览').evaluate((img:HTMLImageElement)=>img.naturalWidth)).toBe(640);
 expect(errors).toEqual([]);
});
