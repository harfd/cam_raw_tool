import {test,expect} from '@playwright/test';
import path from 'node:path';

test('真实样片效果检查、有限自动修正、过期提示和撤销',async({page})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('/');await page.getByRole('button',{name:'导入 NEF 照片'}).click();
 await page.getByLabel('NEF 文件').setInputFiles(path.resolve('DSC_0002.NEF'));
 await page.getByRole('button',{name:'导入并分析原片'}).click();
 await expect(page.getByRole('button',{name:'关闭导入'})).toHaveCount(0);
 await expect(page.getByAltText('原始解码预览')).toBeVisible({timeout:40000});
 await expect(page.locator('#Contrast2012')).toHaveValue('5');
 await page.locator('#Exposure2012').fill('1.5');await page.locator('#Contrast2012').fill('0');await page.locator('#Saturation').fill('0');
 await page.getByRole('checkbox',{name:'保留手动参数数值及手动局部调整'}).uncheck();
 const checked=page.waitForResponse(r=>r.url().endsWith('/quality/check'));
 await page.getByRole('button',{name:'检查当前效果',exact:true}).click();
 const report=(await(await checked).json()).quality_report;
 expect(report.issues.length).toBeGreaterThan(0);
 await expect(page.locator('.quality-result')).toContainText('检测到');
 await page.getByRole('button',{name:'检查并自动修正',exact:true}).click();
 await expect(page.locator('.quality-summary')).toContainText('已有限修正',{timeout:45000});
 await expect(page.getByRole('button',{name:'撤销自动修正',exact:true})).toBeEnabled();
 await page.screenshot({path:'work/ui-quality-workspace.png',fullPage:true});
 await page.locator('#Saturation').fill('8');
 await expect(page.getByText('参数或选区已变化，检查结果已过期，请重新检查。')).toBeVisible();
 await page.getByRole('button',{name:'撤销自动修正',exact:true}).click();
 await expect(page.locator('#Exposure2012')).toHaveValue('1.5');
 await expect(page.locator('#Saturation')).toHaveValue('0');
 expect(errors).toEqual([]);
});
