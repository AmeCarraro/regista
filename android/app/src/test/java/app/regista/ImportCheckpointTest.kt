package app.regista

import org.junit.Assert.*
import org.junit.Test

class ImportCheckpointTest {
    private fun start()=ImportCheckpoint(work="manual",peer="pc",requested=true).prepare(listOf("image:a:1","video:a:2","image:a:3"))
    @Test fun selectionIsFrozenUntilANewExplicitImport() {
        val state=start().prepare(listOf("image:a:1","video:a:2","new-photo"))
        assertEquals(listOf("image:a:1","video:a:2","image:a:3"),state.remaining)
        assertEquals(3,state.total)
    }
    @Test fun acknowledgedFilesAreNotRepeatedAfterResume() {
        val saved=start().confirmed("image:a:1",ImportOutcome.COPIED).confirmed("video:a:2",ImportOutcome.DUPLICATE)
        val resumed=saved.copy(requested=false,phase="paused").copy(requested=true)
        assertEquals(listOf("image:a:3"),resumed.remaining)
        assertEquals(2,resumed.processed)
        assertEquals(1,resumed.copied)
        assertEquals(1,resumed.duplicates)
    }
    @Test fun repeatedOrForeignAcknowledgementsDoNotInflateProgress() {
        val state=start().confirmed("image:a:1",ImportOutcome.COPIED)
        assertEquals(state,state.confirmed("image:a:1",ImportOutcome.DUPLICATE))
        assertEquals(state,state.confirmed("unselected",ImportOutcome.COPIED))
    }
    @Test fun readFailureIsRetainedForExplicitRetry() {
        val failed=start().confirmed("video:a:2",ImportOutcome.FAILED)
        assertTrue("video:a:2" in failed.remaining)
        assertEquals(0,failed.processed)
        assertEquals(1,failed.failed)
        assertEquals(failed,failed.confirmed("video:a:2",ImportOutcome.FAILED))
        val repaired=failed.confirmed("video:a:2",ImportOutcome.COPIED)
        assertEquals(0,repaired.failed)
        assertFalse("video:a:2" in repaired.remaining)
    }
    @Test fun permissionAndPeerChangesDoNotAuthorizeAnotherPC() {
        assertTrue(start().canResume("pc",""))
        assertFalse(start().canResume("other-pc",""))
        assertFalse(start().copy(request="a").canResume("pc","b"))
    }
    @Test fun aPausedDiscoveryKeepsItsWorkIdentityBeforeTheSelectionIsComplete() {
        val partial = ImportCheckpoint(work = "original", peer = "pc", phase = "paused", request = "request")
        assertTrue(partial.canResume("pc", ""))
        assertTrue(partial.canResume("pc", "request"))
        assertFalse(partial.canResume("pc", "another-request"))
        assertFalse(partial.canResume("another-pc", ""))
        assertFalse(partial.copy(phase = "done").canResume("pc", ""))
    }
    @Test fun finalZipCanBeResumedAfterAllBytesWereAcknowledged() {
        val state=start().remaining.fold(start()) { current,id->current.confirmed(id,ImportOutcome.COPIED) }
            .copy(batch="archive",phase="paused")
        assertTrue(state.complete)
        assertTrue(state.canResume("pc",""))
        assertFalse(state.copy(phase="done").canResume("pc",""))
    }
    @Test fun duplicateIdsAreOnlyOneSelectedSource() {
        val state=ImportCheckpoint().prepare(listOf("image:a:1","image:a:1"))
        assertEquals(1,state.total)
    }

    @Test fun largeImportKeepsTheSameSelectionAndTotalsAfterChunkConfirmation() {
        val normal = List(3_797) { "image:primary:${it + 1}" }
        val whatsapp = List(47_199) { "tree:${it + 1}" }
        val groups = mapOf("normal-media" to normal.size, "whatsapp-media" to whatsapp.size)
        val members = normal.associateWith { "normal-media" } + whatsapp.associateWith { "whatsapp-media" }
        val state = ImportCheckpoint(work = "original", peer = "pc", requested = true)
            .prepare(normal + whatsapp).copy(groups = groups, members = members, batch = "existing-block")
        val confirmed = normal.take(99).associateWith { ImportOutcome.DUPLICATE } +
            mapOf(normal[99] to ImportOutcome.COPIED, whatsapp[0] to ImportOutcome.FAILED)
        val next = state.confirmed(confirmed)
        assertEquals(50_996, next.total)
        assertEquals(100, next.processed)
        assertEquals(50_896, next.remaining.size)
        assertEquals(normal.drop(100) + whatsapp, next.remaining)
        assertEquals(groups, next.groups)
        assertEquals(next.remaining.toSet(), next.members.keys)
        assertEquals(listOf(whatsapp[0]), next.failedMedia)
        assertEquals("existing-block", next.batch)
        assertEquals(next, next.confirmed(confirmed))
        assertTrue(next.copy(requested = false, phase = "paused").canResume("pc", ""))
    }
}
