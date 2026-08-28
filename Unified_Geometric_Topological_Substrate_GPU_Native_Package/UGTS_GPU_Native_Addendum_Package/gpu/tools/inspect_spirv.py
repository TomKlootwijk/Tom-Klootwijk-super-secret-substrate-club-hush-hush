#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, struct
from pathlib import Path

OP = {
    15: "OpEntryPoint",
    16: "OpExecutionMode",
    17: "OpCapability",
    71: "OpDecorate",
    72: "OpMemberDecorate",
}
DECORATION = {2:"Block",6:"ArrayStride",11:"BuiltIn",20:"Invariant",24:"NonWritable",25:"NonReadable",33:"Binding",34:"DescriptorSet",35:"Offset"}
EXEC_MODEL = {5:"GLCompute"}
EXEC_MODE = {17:"LocalSize"}
CAPABILITY = {1:"Shader"}

def decode_string(words):
    raw=b''.join(struct.pack('<I',w) for w in words)
    return raw.split(b'\0',1)[0].decode('utf-8','replace')

def inspect(path: Path):
    raw=path.read_bytes()
    if len(raw)%4: raise ValueError(f"{path}: byte length not multiple of 4")
    w=list(struct.unpack('<%dI'%(len(raw)//4),raw))
    if len(w)<5 or w[0]!=0x07230203: raise ValueError(f"{path}: not SPIR-V")
    entries=[]; modes=[]; caps=[]; decorations=[]; hist={}
    i=5; count=0
    while i<len(w):
        opword=w[i]; wc=opword>>16; op=opword&0xffff
        if wc==0 or i+wc>len(w): raise ValueError(f"{path}: malformed instruction at word {i}")
        args=w[i+1:i+wc]
        hist[str(op)]=hist.get(str(op),0)+1
        if op==17 and args: caps.append(CAPABILITY.get(args[0],args[0]))
        elif op==15 and len(args)>=3:
            model=args[0]; entry_id=args[1]; name=decode_string(args[2:])
            # Interface IDs follow the NUL-terminated name; derive its word count.
            name_words=(len(name.encode('utf-8'))+1+3)//4
            entries.append({"execution_model":EXEC_MODEL.get(model,model),"entry_id":entry_id,"name":name,"interface_ids":args[2+name_words:]})
        elif op==16 and len(args)>=2:
            modes.append({"entry_id":args[0],"mode":EXEC_MODE.get(args[1],args[1]),"literals":args[2:]})
        elif op==71 and len(args)>=2:
            decorations.append({"target_id":args[0],"decoration":DECORATION.get(args[1],args[1]),"literals":args[2:]})
        i+=wc;count+=1
    descriptor_bindings=[]
    sets={}; bindings={}
    for d in decorations:
        if d['decoration']=='DescriptorSet' and d['literals']: sets[d['target_id']]=d['literals'][0]
        if d['decoration']=='Binding' and d['literals']: bindings[d['target_id']]=d['literals'][0]
    for target in sorted(set(sets)|set(bindings)):
        descriptor_bindings.append({"target_id":target,"set":sets.get(target),"binding":bindings.get(target)})
    version=w[1]
    return {
        "file":path.name,"sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw),"words":len(w),
        "version_word":f"0x{version:08x}","version":f"{(version>>16)&0xff}.{(version>>8)&0xff}",
        "generator_word":w[2],"id_bound":w[3],"instruction_count":count,
        "capabilities":caps,"entry_points":entries,"execution_modes":modes,"descriptor_bindings":descriptor_bindings,
        "opcode_histogram":hist,
    }

def main():
    ap=argparse.ArgumentParser();ap.add_argument('paths',nargs='+',type=Path);ap.add_argument('-o','--output',type=Path,required=True);args=ap.parse_args()
    report={"schema":"UGTS-SPIRV-MANIFEST-1.1","modules":[inspect(p) for p in args.paths]}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(args.output)
if __name__=='__main__':main()
