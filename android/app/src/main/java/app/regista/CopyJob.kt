package app.regista

import android.app.job.JobParameters
import android.app.job.JobScheduler
import android.app.job.JobService
import android.content.Context

/** Retires previously scheduled automatic copies. New imports always need an explicit user request. */
class CopyJob : JobService() {
    override fun onStartJob(params:JobParameters)=false
    override fun onStopJob(params:JobParameters)=false

    companion object {
        @Suppress("UNUSED_PARAMETER")
        fun plan(context:Context,on:Boolean) { context.getSystemService(JobScheduler::class.java)?.cancel(1) }
    }
}
