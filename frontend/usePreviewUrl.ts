import {useEffect,useState} from 'react';

// A displayed URL belongs to the displayed image, not to the request that
// produced it. Keep it alive while a replacement request is in progress.
export function usePreviewUrl(){
 const [url,setUrl]=useState('');
 useEffect(()=>()=>{if(url)URL.revokeObjectURL(url);},[url]);
 return [url,setUrl] as const;
}
