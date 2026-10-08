export interface DiffLine {text:string;old:number|null;next:number|null;kind:'context'|'addition'|'deletion'|'hunk'|'meta'}
export interface DiffFile {path:string;lines:DiffLine[];additions:number;deletions:number}
export function parseDiff(diff:string):DiffFile[] {
  const result:DiffFile[]=[];let current:DiffFile|null=null,old=0,next=0,oldEnd=0,nextEnd=0,inHunk=false;
  const lines=diff.replace(/\r\n/g,'\n').split('\n');
  for(let i=0;i<lines.length;i++){
    const line=lines[i];
    if(line.startsWith('--- ')&&lines[i+1]?.startsWith('+++ ')&&!inHunk){
      const previous=line.slice(4).split('\t')[0],path=lines[++i].slice(4).split('\t')[0];
      current={path:(path==='/dev/null'?previous:path).replace(/^[ab]\//,''),lines:[],additions:0,deletions:0};result.push(current);continue;
    }
    if(line.startsWith('diff --git ')){inHunk=false;continue;}
    const hunk=line.match(/^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/);
    if(hunk&&current){old=Number(hunk[1]);next=Number(hunk[3]);oldEnd=old+Number(hunk[2]??1);nextEnd=next+Number(hunk[4]??1);inHunk=true;current.lines.push({text:line,old:null,next:null,kind:'hunk'});continue;}
    // A new file header in difflib output follows a blank separator; use hunk
    // line consumption rather than treating source text beginning '---' as a header.
    if(!current)continue;
    if(line.startsWith('\\')){current.lines.push({text:line,old:null,next:null,kind:'meta'});continue;}
    if(!line&&i===lines.length-1)continue;
    if(!inHunk)continue;
    const kind=line[0]==='+'?'addition':line[0]==='-'?'deletion':line[0]===' '?'context':null;
    if(kind){current.lines.push({text:line.slice(1),old:kind==='addition'?null:old++,next:kind==='deletion'?null:next++,kind});if(kind==='addition')current.additions++;if(kind==='deletion')current.deletions++;}
    if(old>=oldEnd&&next>=nextEnd)inHunk=false;
  }
  return result;
}
export function splitLines(lines:DiffLine[]):{left:DiffLine|null;right:DiffLine|null;heading?:DiffLine}[] {
  const rows:ReturnType<typeof splitLines>=[];
  for(let i=0;i<lines.length;i++){
    const line=lines[i];
    if(line.kind==='hunk'||line.kind==='meta'){rows.push({left:null,right:null,heading:line});continue;}
    if(line.kind==='context'){rows.push({left:line,right:line});continue;}
    const removed:DiffLine[]=[],added:DiffLine[]=[];
    while(i<lines.length&&['deletion','addition'].includes(lines[i].kind)){(lines[i].kind==='deletion'?removed:added).push(lines[i]);i++;}i--;
    for(let index=0;index<Math.max(removed.length,added.length);index++)rows.push({left:removed[index]??null,right:added[index]??null});
  }
  return rows;
}
