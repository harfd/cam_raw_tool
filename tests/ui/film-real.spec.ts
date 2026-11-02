import {test,expect} from '@playwright/test';
import path from 'node:path';

test('真实 NEF 胶片预览、反转片直接扫描和图像更新',async({page})=>{
 test.setTimeout(180000);
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('/');await page.getByRole('button',{name:'导入 NEF 照片'}).click();await page.getByLabel('NEF 文件').setInputFiles(path.resolve('DSC_0002.NEF'));await page.getByRole('button',{name:'导入并分析原片'}).click();
 const panel=page.getByRole('region',{name:'胶片模拟'});
 await expect(panel.getByRole('button',{name:'生成胶片预览'})).toBeEnabled({timeout:40000});
 await expect(panel.getByLabel('自动曝光',{exact:true})).toBeChecked();
 await panel.getByRole('button',{name:'生成胶片预览'}).click();
 const image=panel.getByAltText('胶片模拟结果');await expect(image).toBeVisible({timeout:100000});
 await expect.poll(()=>image.evaluate((img:HTMLImageElement)=>img.naturalWidth)).toBe(960);
 const previous=await image.getAttribute('src');
 await panel.screenshot({path:'work/ui-film-portra.png'});
 await panel.getByLabel('胶片型号').selectOption('fujifilm_provia_100f');
 await expect(panel.getByLabel('相纸型号')).toBeDisabled();await expect(panel.getByLabel('冲印曝光',{exact:true})).toBeDisabled();
 await panel.getByRole('button',{name:'生成胶片预览'}).click();
 await expect(image).not.toHaveAttribute('src',previous!,{timeout:100000});
 await expect.poll(()=>image.evaluate((img:HTMLImageElement)=>img.naturalWidth)).toBe(960);
 await expect(panel.getByRole('button',{name:'生成胶片预览'})).toBeEnabled({timeout:100000});
 await panel.screenshot({path:'work/ui-film-provia.png'});
 await expect(panel.locator('[role=alert]')).toHaveCount(0);expect(errors).toEqual([]);
});
