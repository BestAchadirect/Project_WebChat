export const LoadingState = (): JSX.Element => {
    return (
        <div className="flex h-full min-w-[980px] overflow-hidden rounded-3xl border border-slate-200 bg-gray-100 xl:min-w-0">
            <div className="min-h-0 w-[24rem] shrink-0 overflow-hidden border-r border-slate-200 bg-white 2xl:w-[26rem]">
                <div className="animate-pulse p-4">
                    <div className="flex items-center gap-3">
                        <div className="h-10 flex-1 rounded-xl bg-slate-100" />
                        <div className="h-10 w-20 rounded-xl bg-slate-100" />
                    </div>
                    <div className="mt-4 grid grid-cols-3 gap-2">
                        <div className="h-14 rounded-xl bg-slate-100" />
                        <div className="h-14 rounded-xl bg-slate-100" />
                        <div className="h-14 rounded-xl bg-slate-100" />
                    </div>
                </div>
                <div className="space-y-2 p-2">
                    {Array.from({ length: 7 }).map((_, index) => (
                        <div key={index} className="animate-pulse rounded-2xl border border-slate-100 p-4">
                            <div className="h-4 w-28 rounded bg-slate-200" />
                            <div className="mt-2 h-4 w-full rounded bg-slate-100" />
                            <div className="mt-3 h-6 w-24 rounded-full bg-slate-100" />
                        </div>
                    ))}
                </div>
                <div className="border-t border-slate-200 bg-white px-4 py-3">
                    <div className="flex items-center justify-between">
                        <div className="h-4 w-28 animate-pulse rounded bg-slate-100" />
                        <div className="h-8 w-16 animate-pulse rounded-lg bg-slate-100" />
                    </div>
                    <div className="mt-3 flex items-center gap-2">
                        <div className="h-10 w-14 animate-pulse rounded-xl bg-slate-100" />
                        <div className="h-10 flex-1 animate-pulse rounded-xl bg-slate-100" />
                        <div className="h-10 w-14 animate-pulse rounded-xl bg-slate-100" />
                    </div>
                </div>
            </div>

            <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-slate-50">
                <div className="border-b border-slate-200 bg-white px-6 py-5">
                    <div className="h-6 w-40 animate-pulse rounded bg-slate-200" />
                    <div className="mt-2 h-4 w-64 animate-pulse rounded bg-slate-100" />
                </div>
                <div className="space-y-6 p-6">
                    <div className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5">
                        <div className="h-4 w-36 animate-pulse rounded bg-slate-100" />
                        <div className="h-20 w-80 animate-pulse rounded-2xl bg-slate-100" />
                        <div className="ml-auto h-20 w-80 animate-pulse rounded-2xl bg-slate-200" />
                    </div>
                </div>
            </div>
        </div>
    );
};
