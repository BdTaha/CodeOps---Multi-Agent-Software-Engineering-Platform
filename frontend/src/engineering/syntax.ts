import Prism from 'prismjs';
import 'prismjs/components/prism-python';
import 'prismjs/components/prism-typescript';
import 'prismjs/components/prism-jsx';
import 'prismjs/components/prism-tsx';
import 'prismjs/components/prism-java';
import 'prismjs/components/prism-c';
import 'prismjs/components/prism-cpp';
import 'prismjs/components/prism-json';
import 'prismjs/components/prism-yaml';
import 'prismjs/components/prism-bash';
import 'prismjs/components/prism-markdown';

Prism.manual=true;
const languages:Record<string,string>={py:'python',pyw:'python',js:'javascript',mjs:'javascript',cjs:'javascript',ts:'typescript',tsx:'tsx',jsx:'jsx',java:'java',c:'c',h:'c',cpp:'cpp',hpp:'cpp',cc:'cpp',json:'json',yaml:'yaml',yml:'yaml',html:'markup',htm:'markup',xml:'markup',svg:'markup',css:'css',sh:'bash',bash:'bash',zsh:'bash',md:'markdown',markdown:'markdown'};
export interface SyntaxPart {text:string;classes:string}
export function highlightLines(text:string,path:string):SyntaxPart[][] {
  const extension=path.split('.').at(-1)?.toLowerCase()??'';
  const language=languages[extension];
  const grammar=Prism.languages[language];
  if(!grammar||text.length>500_000||text.split('\n').some(line=>line.length>10_000))return text.split('\n').map(line=>[{text:line,classes:''}]);
  const lines:SyntaxPart[][]=[[]];
  function append(content:string|Prism.Token|Array<string|Prism.Token>,classes='') {
    if(Array.isArray(content)){content.forEach(item=>append(item,classes));return;}
    if(typeof content!=='string'){append(content.content,`${classes} ${content.type}`.trim());return;}
    content.split('\n').forEach((piece,index)=>{if(index)lines.push([]);if(piece)lines.at(-1)!.push({text:piece,classes});});
  }
  try {append(Prism.tokenize(text,grammar));return lines;}catch{return text.split('\n').map(line=>[{text:line,classes:''}]);}
}
