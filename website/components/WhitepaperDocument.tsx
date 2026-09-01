import Link from 'next/link';
import type {Locale} from '../content/i18n';

type Block=
 |{kind:'heading';level:number;text:string;id:string}
 |{kind:'paragraph';text:string}
 |{kind:'quote';lines:string[]}
 |{kind:'list';ordered:boolean;items:string[]}
 |{kind:'code';language:string;value:string}
 |{kind:'rule'};

const slug=(value:string,index:number)=>{
 const normalized=value.toLowerCase().replace(/[`*_]/g,'').replace(/[^\p{L}\p{N}]+/gu,'-').replace(/^-|-$/g,'');
 return normalized||`section-${index}`;
};

function parse(source:string):Block[]{
 const lines=source.replace(/\r\n/g,'\n').split('\n');const blocks:Block[]=[];let index=0;const ids=new Map<string,number>();
 const unique=(text:string)=>{const base=slug(text,blocks.length),count=ids.get(base)||0;ids.set(base,count+1);return count?`${base}-${count+1}`:base};
 while(index<lines.length){
  const line=lines[index];
  if(!line.trim()){index++;continue}
  if(line.startsWith('```')){const language=line.slice(3).trim();index++;const body:string[]=[];while(index<lines.length&&!lines[index].startsWith('```'))body.push(lines[index++]);if(index<lines.length)index++;blocks.push({kind:'code',language,value:body.join('\n')});continue}
  const heading=/^(#{1,6})\s+(.+)$/.exec(line);if(heading){blocks.push({kind:'heading',level:heading[1].length,text:heading[2].trim(),id:unique(heading[2])});index++;continue}
  if(/^---+$/.test(line.trim())){blocks.push({kind:'rule'});index++;continue}
  if(line.startsWith('>')){const quote:string[]=[];while(index<lines.length&&lines[index].startsWith('>'))quote.push(lines[index++].replace(/^>\s?/,'').trim());blocks.push({kind:'quote',lines:quote.filter(Boolean)});continue}
  const ordered=/^\d+\.\s+/.test(line);const unordered=/^-\s+/.test(line);if(ordered||unordered){const items:string[]=[];const pattern=ordered?/^\d+\.\s+/:/^-\s+/;while(index<lines.length&&pattern.test(lines[index]))items.push(lines[index++].replace(pattern,'').trim());blocks.push({kind:'list',ordered,items});continue}
  const paragraph=[line.trim()];index++;while(index<lines.length&&lines[index].trim()&&!/^(#{1,6})\s+/.test(lines[index])&&!lines[index].startsWith('```')&&!lines[index].startsWith('>')&&!/^\d+\.\s+/.test(lines[index])&&!/^-\s+/.test(lines[index])&&!/^---+$/.test(lines[index].trim()))paragraph.push(lines[index++].trim());blocks.push({kind:'paragraph',text:paragraph.join(' ')});
 }
 return blocks;
}

function Inline({text}:{text:string}){
 const pieces=text.split(/(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^\s)]+\))/g).filter(Boolean);
 return <>{pieces.map((piece,index)=>{
  if(piece.startsWith('`')&&piece.endsWith('`'))return <code key={index}>{piece.slice(1,-1)}</code>;
  if(piece.startsWith('**')&&piece.endsWith('**'))return <strong key={index}>{piece.slice(2,-2)}</strong>;
  const link=/^\[([^\]]+)\]\(([^\s)]+)\)$/.exec(piece);if(link)return <Link key={index} href={link[2]}>{link[1]}</Link>;
  return <span key={index}>{piece}</span>;
 })}</>;
}

const pageCopy={
 'zh-TW':{contents:'本頁目錄',agent:'Agent／LLM 接入手冊',human:'人類使用白皮書',machine:'此文件是提供外部 LLM 的單一技術版本。'},
 'zh-CN':{contents:'本页目录',agent:'Agent／LLM 接入手册',human:'人类使用白皮书',machine:'此文档是提供给外部 LLM 的单一技术版本。'},
 en:{contents:'On this page',agent:'Agent / LLM integration guide',human:'Human user whitepaper',machine:'This is the single technical edition intended for external LLMs.'}
} as const;

export function WhitepaperDocument({locale,source,kind}:{locale:Locale;source:string;kind:'human'|'agent'}){
 const blocks=parse(source);const toc=blocks.filter((block):block is Extract<Block,{kind:'heading'}>=>block.kind==='heading'&&block.level<=2);const copy=pageCopy[locale];
 return <div className="whitepaper-shell"><aside className="whitepaper-nav" aria-label={copy.contents}><strong>{copy.contents}</strong><ol>{toc.map(item=><li key={item.id} className={`toc-level-${item.level}`}><a href={`#${item.id}`}>{item.text}</a></li>)}</ol></aside><article className="whitepaper-document">{kind==='agent'&&<p className="whitepaper-machine-note">{copy.machine}</p>}{blocks.map((block,index)=>{
  if(block.kind==='heading'){const Tag=`h${Math.min(block.level,6)}` as keyof React.JSX.IntrinsicElements;return <Tag id={block.id} key={block.id}><Inline text={block.text}/></Tag>}
  if(block.kind==='paragraph')return <p key={index}><Inline text={block.text}/></p>;
  if(block.kind==='quote')return <blockquote key={index}>{block.lines.map((line,lineIndex)=><p key={lineIndex}><Inline text={line}/></p>)}</blockquote>;
  if(block.kind==='list'){const Tag=block.ordered?'ol':'ul';return <Tag key={index}>{block.items.map((item,itemIndex)=><li key={itemIndex}><Inline text={item}/></li>)}</Tag>}
  if(block.kind==='code')return <pre key={index} data-language={block.language||undefined}><code>{block.value}</code></pre>;
  return <hr key={index}/>;
 })}<nav className="whitepaper-switch" aria-label="Whitepaper editions">{kind==='human'?<Link href={`/${locale}/whitepaper/agent`}>{copy.agent} →</Link>:<Link href={`/${locale}/whitepaper`}>← {copy.human}</Link>}</nav></article></div>
}
