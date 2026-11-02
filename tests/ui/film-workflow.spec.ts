import {test,expect} from '@playwright/test';
import path from 'node:path';
import {readFile} from 'node:fs/promises';

test('胶片模块独立提交、参数过期提示、取消和成片保存',async({page})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 const image=await readFile(path.resolve('src-tauri/icons/32x32.png'));
 let task:any={status:'idle'},posts=0,hold=false;
 await page.route('**/api/film/catalog',route=>route.fulfill({json:{available:true,films:[{id:'kodak_portra_400',name:'Kodak Portra 400'},{id:'kodak_gold_200',name:'Kodak Gold 200'}],papers:[{id:'kodak_portra_endura',name:'Kodak Portra Endura'}]}}));
 await page.route(/\/api\/jobs\/[a-f0-9]+\/film(?:\/.*)?$/,async route=>{
  const url=route.request().url();
  if(url.endsWith('/render')){posts++;const options=route.request().postDataJSON();task={status:'running',stage:'模拟胶片、冲印和扫描',operation:'f'.repeat(32),options,local_snapshot:[]};await route.fulfill({status:202,json:task});}
  else if(url.endsWith('/cancel')){task={...task,status:'cancelled',stage:'已取消'};await route.fulfill({json:task});}
  else if(url.endsWith('/preview')||url.endsWith('/before'))await route.fulfill({body:image,contentType:'image/png'});
  else if(url.endsWith('/download'))await route.fulfill({body:Buffer.from('test image export'),contentType:'image/tiff'});
  else{if(task.status==='running'&&!hold)task={...task,status:'complete',elapsed_seconds:2,result:{filename:task.options.format==='tiff'?'film-test.tif':'preview.jpg',width:960,height:640,bit_depth:task.options.format==='tiff'?16:8}};await route.fulfill({json:task});}
 });
 await page.goto('/');await page.getByRole('button',{name:'导入 NEF 照片'}).click();await page.getByLabel('NEF 文件').setInputFiles(path.resolve('DSC_0002.NEF'));await page.getByRole('button',{name:'导入并分析原片'}).click();
 const panel=page.getByRole('region',{name:'胶片模拟'});
 await expect(panel.getByRole('button',{name:'生成胶片预览'})).toBeEnabled({timeout:40000});
 await panel.getByRole('button',{name:'生成胶片预览'}).click();
 await expect(panel.getByAltText('胶片模拟结果')).toBeVisible();
 await panel.getByLabel('胶片型号').selectOption('kodak_gold_200');
 await expect(panel.getByText('参数已变化',{exact:false})).toBeVisible();expect(posts).toBe(1);
 hold=true;await panel.getByRole('button',{name:'渲染 16 位 TIFF'}).click();
 await expect(panel.getByRole('button',{name:'取消渲染'})).toBeVisible();
 await expect(panel.getByLabel('胶片曝光',{exact:true})).toBeDisabled();
 await panel.getByRole('button',{name:'取消渲染'}).click();
 await expect(panel.getByRole('button',{name:'生成胶片预览'})).toBeEnabled();
 hold=false;await panel.getByRole('button',{name:'渲染 16 位 TIFF'}).click();
 await expect(panel.getByRole('button',{name:'保存成片'})).toBeVisible();
 const [download]=await Promise.all([page.waitForEvent('download'),panel.getByRole('button',{name:'保存成片'}).click()]);
 expect(download.suggestedFilename()).toBe('film-test.tif');expect(posts).toBe(3);expect(task.options.film).toBe('kodak_gold_200');expect(errors).toEqual([]);
});
