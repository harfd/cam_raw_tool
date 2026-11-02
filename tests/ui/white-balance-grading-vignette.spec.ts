import {test,expect} from '@playwright/test';
import path from 'node:path';
import {readFile} from 'node:fs/promises';

test('白平衡、完整色彩分级、暗角在预览与双模式 XMP 中正确应用',async({page})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('/');await page.getByRole('button',{name:'导入 NEF 照片'}).click();
 await page.getByLabel('NEF 文件').setInputFiles(path.resolve('DSC_0002.NEF'));
 await page.getByLabel('XMP 模板').setInputFiles(path.resolve('DSC_0002.xmp'));
 await page.getByRole('button',{name:'导入并分析原片'}).click();
 await expect(page.getByRole('button',{name:'关闭导入'})).toHaveCount(0);
 await expect(page.locator('#Contrast2012')).toHaveValue('5',{timeout:40000});
 await page.locator('summary').filter({hasText:/^白平衡$/}).click();
 await page.getByLabel('白平衡模式',{exact:true}).selectOption('custom');
 await page.getByLabel('白平衡 · 色温（K）数值',{exact:true}).fill('6500');
 await page.getByLabel('白平衡 · 色温（K）数值',{exact:true}).press('Tab');
 await page.locator('#wb-tint').fill('12');
 await page.locator('summary').filter({hasText:/^色彩分级$/}).click();
 await page.getByRole('button',{name:'中间调',exact:true}).click();
 await page.locator('#ColorGradeMidtoneHue').fill('215');await page.locator('#ColorGradeMidtoneSat').fill('18');await page.locator('#ColorGradeMidtoneLum').fill('9');
 await page.locator('#ColorGradeBlending').fill('75');await page.locator('#SplitToningBalance').fill('12');
 await page.getByRole('button',{name:'阴影',exact:true}).click();await page.locator('#ColorGradeShadowLum').fill('-6');
 await page.getByRole('button',{name:'高光',exact:true}).click();await page.locator('#ColorGradeHighlightLum').fill('5');
 await page.getByRole('button',{name:'全局',exact:true}).click();await page.locator('#ColorGradeGlobalLum').fill('3');
 await page.locator('summary').filter({hasText:/^效果 · 暗角与颗粒$/}).click();
 await page.getByLabel('暗角样式',{exact:true}).selectOption('2');
 for(const [key,value] of Object.entries({PostCropVignetteAmount:-22,PostCropVignetteMidpoint:35,PostCropVignetteRoundness:25,PostCropVignetteFeather:80,PostCropVignetteHighlightContrast:30})){await page.locator('#'+key).fill(String(value));}
 await page.locator('#strength').fill('0.4');
 await expect(page.locator('#PostCropVignetteAmount')).toHaveValue('-22');await expect(page.locator('#wb-temperature')).toHaveValue('6500');
 const checked=page.waitForResponse(r=>r.url().endsWith('/quality/check'));
 await page.getByRole('button',{name:'检查当前效果',exact:true}).click();
 expect((await(await checked).json()).quality_report.basis.state.white_balance.temperature).toBe(6500);
 await expect(page.locator('.quality-result')).toBeVisible();
 const [photo]=await Promise.all([page.waitForEvent('download'),page.getByRole('button',{name:'导出 XMP 预设'}).click()]);
 const filename=path.resolve('work/ui-wb-grading-vignette.xmp');await photo.saveAs(filename);
 const xml=await readFile(filename,'utf8');
 for(const [key,value] of Object.entries({WhiteBalance:'Custom',Temperature:6500,Tint:12,ColorGradeMidtoneHue:215,ColorGradeMidtoneSat:18,ColorGradeMidtoneLum:9,ColorGradeShadowLum:-6,ColorGradeHighlightLum:5,ColorGradeGlobalLum:3,ColorGradeBlending:75,SplitToningBalance:12,PostCropVignetteStyle:2,PostCropVignetteAmount:-22,PostCropVignetteMidpoint:35,PostCropVignetteRoundness:25,PostCropVignetteFeather:80,PostCropVignetteHighlightContrast:30})){expect(xml).toContain(`crs:${key}="${value}"`);}
 await page.screenshot({path:'work/ui-wb-grading-vignette.png',fullPage:true});
 await page.getByRole('button',{name:'通用风格',exact:false}).click();
 await expect(page.getByLabel('白平衡模式',{exact:true})).toBeDisabled();await expect(page.locator('#wb-temperature')).toHaveCount(0);
 const [style]=await Promise.all([page.waitForEvent('download'),page.getByRole('button',{name:'导出 XMP 预设'}).click()]);
 const target=path.resolve('work/ui-wb-reusable.xmp');await style.saveAs(target);
 const reusable=await readFile(target,'utf8');expect(reusable).not.toContain('crs:WhiteBalance=');expect(reusable).not.toContain('crs:Temperature=');expect(reusable).not.toContain('crs:Tint=');
 expect(errors).toEqual([]);
});
