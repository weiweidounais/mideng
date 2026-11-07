type Read = <T>(path:string, init?:RequestInit) => Promise<T>;

// Commit one complete response in the caller, rather than mixing an updated
// library list with documents left over from an earlier request.
export async function readKnowledgeSnapshot<L extends {id:string}, D, A>(
  read:Read, base:string, libraryId:string|undefined, signal?:AbortSignal,
) {
  const libraries=await read<L[]>(base+'/libraries',{signal});
  if(!libraryId||!libraries.some(item=>item.id===libraryId)) {
    return {libraries,documents:[] as D[],applications:[] as A[],accessible:false};
  }
  const path=base+'/libraries/'+libraryId;
  const [documents,applications]=await Promise.all([
    read<{items:D[]}>(path+'/documents',{signal}),read<A[]>(path+'/applications',{signal}),
  ]);
  return {libraries,documents:documents.items,applications,accessible:true};
}
